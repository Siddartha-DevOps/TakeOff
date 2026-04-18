import React, { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { CheckCircle, Loader2, XCircle, ArrowRight } from 'lucide-react';
import { paymentsAPI } from '../services/api';

export default function PaymentSuccess() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [status, setStatus] = useState('checking'); // checking, success, failed
  const [paymentData, setPaymentData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const sessionId = searchParams.get('session_id');
    if (!sessionId) {
      setStatus('failed');
      setError('No session ID found');
      return;
    }

    pollPaymentStatus(sessionId);
  }, [searchParams]);

  const pollPaymentStatus = async (sessionId, attempts = 0) => {
    const maxAttempts = 5;
    const pollInterval = 2000; // 2 seconds

    if (attempts >= maxAttempts) {
      setStatus('failed');
      setError('Payment status check timed out. Please check your email for confirmation.');
      return;
    }

    try {
      const response = await paymentsAPI.getCheckoutStatus(sessionId);
      const data = response.data;

      if (data.payment_status === 'paid') {
        setStatus('success');
        setPaymentData(data);
        return;
      } else if (data.status === 'expired') {
        setStatus('failed');
        setError('Payment session expired. Please try again.');
        return;
      }

      // If payment is still pending, continue polling
      setTimeout(() => pollPaymentStatus(sessionId, attempts + 1), pollInterval);
    } catch (err) {
      console.error('Error checking payment status:', err);
      setStatus('failed');
      setError(err.response?.data?.detail || 'Error checking payment status. Please try again.');
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 flex items-center justify-center px-6">
      <div className="max-w-md w-full">
        {status === 'checking' && (
          <div className="bg-white rounded-2xl shadow-xl p-8 text-center">
            <div className="w-16 h-16 mx-auto bg-indigo-100 rounded-full flex items-center justify-center">
              <Loader2 className="w-8 h-8 text-indigo-600 animate-spin" />
            </div>
            <h2 className="mt-6 text-2xl font-semibold text-slate-900">Verifying your payment...</h2>
            <p className="mt-2 text-sm text-slate-600">Please wait while we confirm your subscription.</p>
          </div>
        )}

        {status === 'success' && (
          <div className="bg-white rounded-2xl shadow-xl p-8 text-center animate-fade-up">
            <div className="w-16 h-16 mx-auto bg-emerald-100 rounded-full flex items-center justify-center">
              <CheckCircle className="w-8 h-8 text-emerald-600" />
            </div>
            <h2 className="mt-6 text-2xl font-semibold text-slate-900">Payment successful!</h2>
            <p className="mt-2 text-sm text-slate-600">
              Thank you for subscribing to TakeOff.ai. Your account has been upgraded.
            </p>
            
            {paymentData && (
              <div className="mt-6 p-4 bg-slate-50 rounded-lg text-left">
                <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Payment Details</div>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-slate-600">Plan</span>
                    <span className="font-semibold text-slate-900 capitalize">
                      {paymentData.metadata?.package_name || 'Subscription'}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-600">Amount</span>
                    <span className="font-semibold text-slate-900">
                      ${paymentData.amount?.toFixed(2)} {paymentData.currency?.toUpperCase()}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-600">Status</span>
                    <span className="inline-flex items-center gap-1 text-emerald-600 font-semibold">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                      Paid
                    </span>
                  </div>
                </div>
              </div>
            )}

            <div className="mt-8 flex flex-col gap-3">
              <button
                onClick={() => navigate('/app')}
                className="w-full inline-flex items-center justify-center gap-2 px-6 py-3 rounded-lg bg-slate-900 text-white font-medium hover:bg-slate-800 transition-colors"
              >
                Go to Dashboard <ArrowRight className="w-4 h-4" />
              </button>
              <button
                onClick={() => navigate('/pricing')}
                className="w-full px-6 py-3 rounded-lg bg-slate-100 text-slate-700 font-medium hover:bg-slate-200 transition-colors"
              >
                View Pricing
              </button>
            </div>
          </div>
        )}

        {status === 'failed' && (
          <div className="bg-white rounded-2xl shadow-xl p-8 text-center">
            <div className="w-16 h-16 mx-auto bg-red-100 rounded-full flex items-center justify-center">
              <XCircle className="w-8 h-8 text-red-600" />
            </div>
            <h2 className="mt-6 text-2xl font-semibold text-slate-900">Payment verification failed</h2>
            <p className="mt-2 text-sm text-slate-600">{error || 'Something went wrong. Please try again.'}</p>
            
            <div className="mt-8 flex flex-col gap-3">
              <button
                onClick={() => navigate('/pricing')}
                className="w-full px-6 py-3 rounded-lg bg-slate-900 text-white font-medium hover:bg-slate-800 transition-colors"
              >
                Try Again
              </button>
              <button
                onClick={() => navigate('/app')}
                className="w-full px-6 py-3 rounded-lg bg-slate-100 text-slate-700 font-medium hover:bg-slate-200 transition-colors"
              >
                Back to Dashboard
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

