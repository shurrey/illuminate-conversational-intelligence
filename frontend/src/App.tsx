/**
 * Illuminate Conversational Intelligence - Main App Component
 */

import React, { useEffect, useState } from 'react';
import { AppShell } from './components/layout/AppShell';
import { ChatContainer } from './components/chat/ChatContainer';
import { authService } from './services/authService';

function App() {
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    // Auto-login in development mode
    if (import.meta.env.DEV || import.meta.env.VITE_MOCK_MODE === 'true') {
      if (!authService.isAuthenticated()) {
        authService.devLogin();
      }
    }
    setIsReady(true);
  }, []);

  if (!isReady) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-50">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
      </div>
    );
  }

  return (
    <AppShell>
      <ChatContainer className="h-full" />
    </AppShell>
  );
}

export default App;
