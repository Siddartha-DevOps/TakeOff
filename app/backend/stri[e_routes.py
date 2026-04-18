from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
import schemas
import models
from auth import get_current_user
from database import get_db
import json
import os
from datetime import datetime, timezone
from emergentintegrations.payments.stripe.checkout import StripeCheckout, CheckoutSessionResponse, CheckoutStatusResponse, CheckoutSessionRequest

router = APIRouter(prefix="/payments", tags=["Payments"])

# Fixed subscription packages (SECURITY: Never accept amounts from frontend)
SUBSCRIPTION_PACKAGES = {
    "starter": {
        "name": "Starter",
        "amount": 199.00,
        "currency": "usd",
        "description": "For solo estimators getting started with AI"
    },
    "growth": {
        "name": "Growth",
        "amount": 299.00,
        "currency": "usd",
        "description": "Built for small estimating teams winning more bids"
    }
}

def get_stripe_checkout(request: Request):
    """Initialize Stripe checkout with webhook URL"""
    api_key = os.environ.get('STRIPE_API_KEY')
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stripe API key not configured"
        )
    
    # Build webhook URL from request base URL
    host_url = str(request.base_url).rstrip('/')
    webhook_url = f"{host_url}/api/webhook/stripe"
    
    return StripeCheckout(api_key=api_key, webhook_url=webhook_url)

@router.post("/checkout/session")
async def create_checkout_session(
    package_id: str,
    origin_url: str,
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create Stripe checkout session for subscription
    Frontend sends: packageId and originUrl only
    Backend defines all pricing and builds URLs
    """
    # Validate package
    if package_id not in SUBSCRIPTION_PACKAGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid package. Must be one of: {list(SUBSCRIPTION_PACKAGES.keys())}"
        )
    
    package = SUBSCRIPTION_PACKAGES[package_id]
    
    # Build dynamic success/cancel URLs from frontend origin
    success_url = f"{origin_url}/payment-success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{origin_url}/pricing"
    
    # Prepare metadata
    metadata = {
        "user_id": str(current_user.id),
        "user_email": current_user.email,
        "package_id": package_id,
        "package_name": package["name"]
    }
    
    try:
        # Initialize Stripe checkout
        stripe_checkout = get_stripe_checkout(request)
        
        # Create checkout session request
        checkout_request = CheckoutSessionRequest(
            amount=package["amount"],
            currency=package["currency"],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=metadata
        )
        
        # Create checkout session with Stripe
        session: CheckoutSessionResponse = await stripe_checkout.create_checkout_session(checkout_request)
        
        # MANDATORY: Create payment transaction record BEFORE redirect
        payment_transaction = models.PaymentTransaction(
            session_id=session.session_id,
            user_id=current_user.id,
            amount=package["amount"],
            currency=package["currency"],
            payment_status="pending",
            status="initiated",
            payment_metadata=json.dumps(metadata)
        )
        db.add(payment_transaction)
        db.commit()
        
        return {
            "url": session.url,
            "session_id": session.session_id
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create checkout session: {str(e)}"
        )

@router.get("/checkout/status/{session_id}")
async def get_checkout_status(
    session_id: str,
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Poll payment status from Stripe
    Called by frontend after redirect from Stripe
    """
    # Get payment transaction
    transaction = db.query(models.PaymentTransaction).filter(
        models.PaymentTransaction.session_id == session_id,
        models.PaymentTransaction.user_id == current_user.id
    ).first()
    
    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment transaction not found"
        )
    
    # If already processed, return cached status
    if transaction.payment_status == "paid" and transaction.status == "completed":
        return {
            "status": transaction.status,
            "payment_status": transaction.payment_status,
            "amount": transaction.amount,
            "currency": transaction.currency,
            "metadata": json.loads(transaction.payment_metadata) if transaction.payment_metadata else {}
        }
    
    try:
        # Check status with Stripe
        stripe_checkout = get_stripe_checkout(request)
        checkout_status: CheckoutStatusResponse = await stripe_checkout.get_checkout_status(session_id)
        
        # Update transaction status
        transaction.payment_status = checkout_status.payment_status
        transaction.status = checkout_status.status
        transaction.updated_at = datetime.now(timezone.utc)
        
        # If payment successful and not already processed, create subscription
        if checkout_status.payment_status == "paid" and transaction.status != "completed":
            metadata = json.loads(transaction.payment_metadata) if transaction.payment_metadata else {}
            package_id = metadata.get("package_id")
            
            if package_id and package_id in SUBSCRIPTION_PACKAGES:
                # Create or update user subscription
                existing_subscription = db.query(models.UserSubscription).filter(
                    models.UserSubscription.user_id == current_user.id,
                    models.UserSubscription.status == "active"
                ).first()
                
                if existing_subscription:
                    # Update existing subscription
                    existing_subscription.plan_name = package_id
                    existing_subscription.amount = SUBSCRIPTION_PACKAGES[package_id]["amount"]
                    existing_subscription.stripe_session_id = session_id
                    existing_subscription.updated_at = datetime.now(timezone.utc)
                else:
                    # Create new subscription
                    subscription = models.UserSubscription(
                        user_id=current_user.id,
                        plan_name=package_id,
                        status="active",
                        stripe_session_id=session_id,
                        amount=SUBSCRIPTION_PACKAGES[package_id]["amount"],
                        currency=SUBSCRIPTION_PACKAGES[package_id]["currency"]
                    )
                    db.add(subscription)
            
            # Mark transaction as completed
            transaction.status = "completed"
        
        db.commit()
        
        return {
            "status": checkout_status.status,
            "payment_status": checkout_status.payment_status,
            "amount": checkout_status.amount_total / 100,  # Convert cents to dollars
            "currency": checkout_status.currency,
            "metadata": checkout_status.metadata
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check payment status: {str(e)}"
        )

@router.get("/subscription")
async def get_user_subscription(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get current user's active subscription"""
    subscription = db.query(models.UserSubscription).filter(
        models.UserSubscription.user_id == current_user.id,
        models.UserSubscription.status == "active"
    ).order_by(models.UserSubscription.created_at.desc()).first()
    
    if not subscription:
        return {
            "has_subscription": False,
            "plan_name": None
        }
    
    return {
        "has_subscription": True,
        "plan_name": subscription.plan_name,
        "amount": subscription.amount,
        "currency": subscription.currency,
        "status": subscription.status,
        "started_at": subscription.started_at
    }

@router.post("/webhook/stripe")
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Handle Stripe webhook events
    Stripe will call this endpoint for payment events
    """
    try:
        # Get raw body and signature
        body = await request.body()
        signature = request.headers.get("Stripe-Signature")
        
        if not signature:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing Stripe signature"
            )
        
        # Initialize Stripe checkout
        stripe_checkout = get_stripe_checkout(request)
        
        # Handle webhook
        webhook_response = await stripe_checkout.handle_webhook(body, signature)
        
        # Process webhook event
        if webhook_response.event_type in ["checkout.session.completed", "payment_intent.succeeded"]:
            # Update transaction status
            transaction = db.query(models.PaymentTransaction).filter(
                models.PaymentTransaction.session_id == webhook_response.session_id
            ).first()
            
            if transaction:
                transaction.payment_status = webhook_response.payment_status
                transaction.status = "completed"
                transaction.updated_at = datetime.now(timezone.utc)
                db.commit()
        
        return {"status": "success", "event_type": webhook_response.event_type}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Webhook error: {str(e)}"
        )

