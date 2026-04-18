from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
import schemas
import models
from auth import get_current_user
from database import get_db
import json
import os
import stripe
from datetime import datetime, timezone

router = APIRouter(prefix="/payments", tags=["Payments"])

# Fixed subscription packages (SECURITY: Never accept amounts from frontend)
SUBSCRIPTION_PACKAGES = {
    "starter": {
        "name": "Starter",
        "amount": 19900,  # in cents
        "currency": "usd",
        "description": "For solo estimators getting started with AI"
    },
    "growth": {
        "name": "Growth",
        "amount": 29900,  # in cents
        "currency": "usd",
        "description": "Built for small estimating teams winning more bids"
    }
}

def get_stripe_client():
    api_key = os.environ.get('STRIPE_API_KEY')
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stripe API key not configured"
        )
    stripe.api_key = api_key
    return stripe

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
    if package_id not in SUBSCRIPTION_PACKAGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid package. Must be one of: {list(SUBSCRIPTION_PACKAGES.keys())}"
        )

    package = SUBSCRIPTION_PACKAGES[package_id]

    success_url = f"{origin_url}/payment-success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{origin_url}/pricing"

    metadata = {
        "user_id": str(current_user.id),
        "user_email": current_user.email,
        "package_id": package_id,
        "package_name": package["name"]
    }

    try:
        get_stripe_client()

        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": package["currency"],
                    "unit_amount": package["amount"],
                    "product_data": {
                        "name": package["name"],
                        "description": package["description"]
                    }
                },
                "quantity": 1
            }],
            mode="payment",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=metadata
        )

        # MANDATORY: Create payment transaction record BEFORE redirect
        payment_transaction = models.PaymentTransaction(
            session_id=session.id,
            user_id=current_user.id,
            amount=package["amount"] / 100,
            currency=package["currency"],
            payment_status="pending",
            status="initiated",
            payment_metadata=json.dumps(metadata)
        )
        db.add(payment_transaction)
        db.commit()

        return {
            "url": session.url,
            "session_id": session.id
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
    transaction = db.query(models.PaymentTransaction).filter(
        models.PaymentTransaction.session_id == session_id,
        models.PaymentTransaction.user_id == current_user.id
    ).first()

    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment transaction not found"
        )

    if transaction.payment_status == "paid" and transaction.status == "completed":
        return {
            "status": transaction.status,
            "payment_status": transaction.payment_status,
            "amount": transaction.amount,
            "currency": transaction.currency,
            "metadata": json.loads(transaction.payment_metadata) if transaction.payment_metadata else {}
        }

    try:
        get_stripe_client()
        session = stripe.checkout.Session.retrieve(session_id)

        transaction.payment_status = session.payment_status
        transaction.status = session.status
        transaction.updated_at = datetime.now(timezone.utc)

        if session.payment_status == "paid" and transaction.status != "completed":
            metadata = json.loads(transaction.payment_metadata) if transaction.payment_metadata else {}
            package_id = metadata.get("package_id")

            if package_id and package_id in SUBSCRIPTION_PACKAGES:
                existing_subscription = db.query(models.UserSubscription).filter(
                    models.UserSubscription.user_id == current_user.id,
                    models.UserSubscription.status == "active"
                ).first()

                if existing_subscription:
                    existing_subscription.plan_name = package_id
                    existing_subscription.amount = SUBSCRIPTION_PACKAGES[package_id]["amount"] / 100
                    existing_subscription.stripe_session_id = session_id
                    existing_subscription.updated_at = datetime.now(timezone.utc)
                else:
                    subscription = models.UserSubscription(
                        user_id=current_user.id,
                        plan_name=package_id,
                        status="active",
                        stripe_session_id=session_id,
                        amount=SUBSCRIPTION_PACKAGES[package_id]["amount"] / 100,
                        currency=SUBSCRIPTION_PACKAGES[package_id]["currency"]
                    )
                    db.add(subscription)

            transaction.status = "completed"

        db.commit()

        return {
            "status": session.status,
            "payment_status": session.payment_status,
            "amount": session.amount_total / 100,
            "currency": session.currency,
            "metadata": session.metadata
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
        body = await request.body()
        signature = request.headers.get("Stripe-Signature")

        if not signature:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing Stripe signature"
            )

        get_stripe_client()
        webhook_secret = os.environ.get('STRIPE_WEBHOOK_SECRET', '')

        if webhook_secret:
            event = stripe.Webhook.construct_event(body, signature, webhook_secret)
        else:
            event = stripe.Event.construct_from(json.loads(body), stripe.api_key)

        if event["type"] in ["checkout.session.completed", "payment_intent.succeeded"]:
            session_obj = event["data"]["object"]
            transaction = db.query(models.PaymentTransaction).filter(
                models.PaymentTransaction.session_id == session_obj.get("id")
            ).first()

            if transaction:
                transaction.payment_status = session_obj.get("payment_status", "paid")
                transaction.status = "completed"
                transaction.updated_at = datetime.now(timezone.utc)
                db.commit()

        return {"status": "success", "event_type": event["type"]}

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Webhook error: {str(e)}"
        )