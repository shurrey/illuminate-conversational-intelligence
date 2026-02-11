/**
 * Illuminate Conversational Intelligence - Main App Component
 */

import { useState, useEffect } from 'react';
import { AppShell } from './components/layout/AppShell';
import { ChatContainer } from './components/chat/ChatContainer';
import { Login } from './components/auth/Login';
import { authService } from './services/authService';

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // Check if already authenticated
    setIsAuthenticated(authService.isAuthenticated());
    setIsLoading(false);
  }, []);

  const handleLoginSuccess = () => {
    setIsAuthenticated(true);
  };

  const handleLogout = () => {
    authService.logout();
    setIsAuthenticated(false);
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-50">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Login onLoginSuccess={handleLoginSuccess} />;
  }

  return (
    <AppShell onLogout={handleLogout}>
      <ChatContainer className="h-full" />
    </AppShell>
  );
}

export default App;
