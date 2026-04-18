import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Send, Sparkles, Loader2 } from 'lucide-react';

// Mock responses for the chat widget
const CHAT_RESPONSES = {
  pricing: {
    keywords: ['price', 'pricing', 'cost', 'plan', 'pay', 'subscription', 'affordable'],
    answer: 'TakeOff.ai has 3 plans: **Starter** at $199/mo (10 projects), **Growth** at $299/mo (unlimited), and **Business** (custom pricing). All plans include a 14-day free trial. Check out our [Pricing page](/pricing) for full details!',
  },
  features: {
    keywords: ['feature', 'what can', 'capabilities', 'do', 'functionality', 'tools'],
    answer: 'TakeOff.ai offers AI-powered room & area detection, real-time collaboration, revision comparison, TakeOff Chat (AI assistant), smart exports (Excel/CSV), and supports all file types (PDF, TIFF, PNG). See all [Features here](/features)!',
  },
  demo: {
    keywords: ['demo', 'trial', 'try', 'test', 'see it', 'show me'],
    answer: 'You can book a personalized demo with our team or start a free 14-day trial instantly! No credit card needed. [Book a demo](/demo) or [Start free trial](/app).',
  },
  accuracy: {
    keywords: ['accuracy', 'reliable', 'confident', 'precise', 'trust'],
    answer: 'TakeOff.ai delivers **98% detection accuracy** across rooms, doors, windows, and fixtures. Every detection includes a confidence score so you can review and verify results.',
  },
  comparison: {
    keywords: ['vs', 'compare', 'better', 'difference', 'bluebeam', 'planswift', 'ost'],
    answer: 'Unlike legacy tools, TakeOff.ai is cloud-native, AI-powered, and built for real-time collaboration. We outperform Bluebeam, PlanSwift, and OST in speed, accuracy, and ease of use. [See full comparison](/compare/bluebeam).',
  },
  trades: {
    keywords: ['trade', 'drywall', 'electrical', 'plumbing', 'mechanical', 'painting'],
    answer: 'TakeOff.ai supports all major trades: Drywall, Electrical, Plumbing, Mechanical/HVAC, Painting, Flooring, Glazing, and more. Learn more about [Trades we support](/trades).',
  },
  support: {
    keywords: ['help', 'support', 'contact', 'question', 'assistance'],
    answer: 'We offer email support on Starter, priority 20-min SLA support on Growth, and dedicated CSM on Business plans. You can also reach us at support@takeoff.ai.',
  },
  navigation: {
    keywords: ['where', 'find', 'page', 'navigate', 'go to'],
    answer: 'You can navigate to:
- [Home](/)
- [Features](/features)
- [Trades](/trades)
- [Pricing](/pricing)
- [Compare](/compare/bluebeam)
- [About](/about)
- [App Dashboard](/app)',
  },
  default: {
    keywords: [],
    answer: 'Thanks for asking! I can help you with:

✨ Product features & capabilities
💰 Pricing & plans
🎯 Accuracy & reliability
📊 Trade support
🚀 Demos & trials
📍 Site navigation

What would you like to know?',
  },
};

function findBestResponse(message) {
  const lowerMsg = message.toLowerCase();
  for (const [key, data] of Object.entries(CHAT_RESPONSES)) {
    if (data.keywords.some(kw => lowerMsg.includes(kw))) {
      return data.answer;
    }
  }
  return CHAT_RESPONSES.default.answer;
}

export default function ChatWidget() {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState([
    { role: 'assistant', text: 'Hi! I\'m here to help you learn about TakeOff.ai. Ask me anything about pricing, features, or how it works!', time: 'now' },
  ]);
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const endRef = useRef(null);

  useEffect(() => {
    if (isOpen && endRef.current) {
      endRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isOpen, isTyping]);

  async function handleSend() {
    const text = input.trim();
    if (!text || isTyping) return;

    setMessages(m => [...m, { role: 'user', text, time: 'now' }]);
    setInput('');
    setIsTyping(true);

    await new Promise(r => setTimeout(r, 800));
    const response = findBestResponse(text);
    setMessages(m => [...m, { role: 'assistant', text: response, time: 'now' }]);
    setIsTyping(false);
  }

  return (
    <>
      {/* Floating button */}
      <AnimatePresence>
        {!isOpen && (
          <motion.button
            initial={{ scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0, opacity: 0 }}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            onClick={() => setIsOpen(true)}
            className=\"fixed bottom-6 right-6 z-[9999] w-14 h-14 rounded-full bg-gradient-to-br from-indigo-500 via-violet-500 to-blue-500 text-white shadow-2xl shadow-indigo-500/40 flex items-center justify-center group\"
          >
            <Sparkles className=\"w-6 h-6 group-hover:rotate-12 transition-transform\" />
            <span className=\"absolute -top-1 -right-1 w-3 h-3 bg-rose-500 rounded-full animate-pulse\" />
          </motion.button>
        )}
      </AnimatePresence>

      {/* Chat window */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: 20, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.95 }}
            transition={{ duration: 0.2 }}
            className=\"fixed bottom-6 right-6 z-[9999] w-[380px] h-[600px] bg-white rounded-2xl shadow-2xl shadow-slate-900/20 border border-slate-200 flex flex-col overflow-hidden\"
          >
            {/* Header */}
            <div className=\"flex items-center justify-between px-5 py-4 bg-gradient-to-r from-indigo-500 via-violet-500 to-blue-500 text-white\">
              <div className=\"flex items-center gap-3\">
                <div className=\"w-10 h-10 rounded-full bg-white/20 backdrop-blur flex items-center justify-center\">
                  <Sparkles className=\"w-5 h-5\" />
                </div>
                <div>
                  <div className=\"font-semibold text-sm\">TakeOff Assistant</div>
                  <div className=\"flex items-center gap-1.5 text-xs text-white/80\">
                    <span className=\"w-1.5 h-1.5 rounded-full bg-emerald-400\" />
                    Online now
                  </div>
                </div>
              </div>
              <button
                onClick={() => setIsOpen(false)}
                className=\"w-8 h-8 rounded-lg hover:bg-white/20 flex items-center justify-center transition-colors\"
              >
                <X className=\"w-4 h-4\" />
              </button>
            </div>

            {/* Messages */}
            <div className=\"flex-1 overflow-auto p-4 space-y-3 bg-slate-50\">
              {messages.map((msg, i) => (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.2 }}
                  className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  <div
                    className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm ${
                      msg.role === 'user'
                        ? 'bg-indigo-600 text-white rounded-br-md'
                        : 'bg-white text-slate-900 border border-slate-200 rounded-bl-md'
                    }`}
                    dangerouslySetInnerHTML={{
                      __html: msg.text
                        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                        .replace(/\[(.*?)\]\((.*?)\)/g, '<a href=\"$2\" class=\"underline\">$1</a>')
                        .replace(/
/g, '<br />'),
                    }}
                  />
                </motion.div>
              ))}
              {isTyping && (
                <motion.div
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  className=\"flex justify-start\"
                >
                  <div className=\"bg-white border border-slate-200 rounded-2xl rounded-bl-md px-4 py-2.5 flex items-center gap-2\">
                    <Loader2 className=\"w-4 h-4 animate-spin text-indigo-600\" />
                    <span className=\"text-sm text-slate-500\">Typing...</span>
                  </div>
                </motion.div>
              )}
              <div ref={endRef} />
            </div>

            {/* Input */}
            <div className=\"p-4 bg-white border-t border-slate-200\">
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  handleSend();
                }}
                className=\"flex items-center gap-2\"
              >
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder=\"Ask about pricing, features...\"
                  className=\"flex-1 px-4 py-2.5 text-sm rounded-xl border border-slate-300 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200 outline-none\"
                  disabled={isTyping}
                />
                <button
                  type=\"submit\"
                  disabled={!input.trim() || isTyping}
                  className=\"w-10 h-10 rounded-xl bg-indigo-600 text-white flex items-center justify-center disabled:opacity-40 disabled:cursor-not-allowed hover:bg-indigo-700 transition-colors\"
                >
                  <Send className=\"w-4 h-4\" />
                </button>
              </form>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
"