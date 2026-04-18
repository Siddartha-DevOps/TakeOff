import React from 'react';
import './App.css';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Navbar from './components/Navbar';
import Footer from './components/Footer';
import ChatWidget from './components/ChatWidget';
import ProtectedRoute from './components/ProtectedRoute';
import { AuthProvider } from './context/AuthContext';
import Home from './pages/Home';
import Features from './pages/Features';
import Trades from './pages/Trades';
import Pricing from './pages/Pricing';
import About from './pages/About';
import Comparison from './pages/Comparison';
import Demo from './pages/Demo';
import Login from './pages/Login';
import Signup from './pages/Signup';
import Dashboard from './pages/Dashboard';
import Takeoff from './pages/Takeoff';
import Blog from './pages/Blog';
import { Toaster } from './components/ui/sonner';
import PaymentSuccess from './pages/PaymentSuccess';


function MarketingShell({ children }) {
  return (
    <>
      <Navbar />
      <main className="pt-16">{children}</main>
      <Footer />
    </>
  );
}

function App() {
  return (
    <div className="App min-h-screen bg-white text-slate-900">
      <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/" element={<MarketingShell><Home /></MarketingShell>} />
          <Route path="/features" element={<MarketingShell><Features /></MarketingShell>} />
          <Route path="/trades" element={<MarketingShell><Trades /></MarketingShell>} />
          <Route path="/pricing" element={<MarketingShell><Pricing /></MarketingShell>} />
          <Route path="/about" element={<MarketingShell><About /></MarketingShell>} />
          <Route path="/compare/:competitor" element={<MarketingShell><Comparison /></MarketingShell>} />
          <Route path="/demo" element={<MarketingShell><Demo /></MarketingShell>} />
          <Route path="/blog" element={<MarketingShell><Blog /></MarketingShell>} />
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          <Route path=\"/payment-success\" element={<ProtectedRoute><PaymentSuccess /></ProtectedRoute>} />
          <Route path=\"/app\" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
          <Route path=\"/app/projects/:id\" element={<ProtectedRoute><Takeoff /></ProtectedRoute>} />
        </Routes>
         <ChatWidget />
         <AuthProvider>
      </BrowserRouter>
      <Toaster />
    </div>
  );
}

export default App;

