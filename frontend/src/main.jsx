import { lazy, Suspense } from "react";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useParams } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth";
import Layout from "./components/Layout";
import { Loading } from "./components/ui";
import Dashboard from "./pages/Dashboard";
import { Login, Register, ForgotPassword, ResetPassword } from "./pages/Auth";
import Notifications from "./pages/Notifications";
import Chats from "./pages/Chats";

// AG Grid is large: the All records page loads it only when opened
const AllRecords = lazy(() => import("./pages/AllRecords"));
import PayPalCallback from "./pages/PayPalCallback";
import Person from "./pages/Person";
import Profile from "./pages/Profile";
import Search from "./pages/Search";
import Review from "./pages/Review";
import Settings from "./pages/Settings";
import "./styles.css";

// the separate business page was removed: old links open the business on the dashboard
function BusinessRedirect() {
  const { id } = useParams();
  return <Navigate to={`/?biz=${id}`} replace />;
}

function Protected() {
  const { user, loading } = useAuth();
  if (loading) return <Loading />;
  return user ? <Layout /> : <Navigate to="/login" replace />;
}

function PublicOnly({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <Loading />;
  return user ? <Navigate to="/" replace /> : children;
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<PublicOnly><Login /></PublicOnly>} />
          <Route path="/register" element={<PublicOnly><Register /></PublicOnly>} />
          <Route path="/paypal/callback" element={<PayPalCallback />} />
          <Route path="/forgot-password" element={<PublicOnly><ForgotPassword /></PublicOnly>} />
          <Route path="/reset-password" element={<PublicOnly><ResetPassword /></PublicOnly>} />
          <Route element={<Protected />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/businesses/:id" element={<BusinessRedirect />} />
            <Route path="/records/:id" element={<Person />} />
            <Route path="/review" element={<Review />} />
            <Route path="/notifications" element={<Notifications />} />
            <Route path="/all-records" element={<Suspense fallback={<div className="page-loading"><span className="spinner" /></div>}><AllRecords /></Suspense>} />
            <Route path="/chats" element={<Chats />} />
            <Route path="/chats/:id" element={<Chats />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/profile" element={<Profile />} />
            <Route path="/search" element={<Search />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  </React.StrictMode>
);
