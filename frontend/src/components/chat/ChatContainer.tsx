/**
 * ChatContainer - Main chat interface component.
 *
 * Provides the complete chat experience including:
 * - Message list with auto-scroll
 * - Input area with suggestions
 * - Loading indicators
 */

import { useChat } from '../../hooks/useChat';
import { MessageList } from './MessageList';
import { InputArea } from './InputArea';
import { TypingIndicator } from './TypingIndicator';
import { ThinkingBubble } from './ThinkingBubble';
import type { QuerySuggestion } from '../../types/message';

const DEFAULT_SUGGESTIONS: QuerySuggestion[] = [
  { id: '1', text: "What's the average GPA for Fall 2024?", category: 'grades' },
  { id: '2', text: 'Show enrollment trends by department', category: 'students' },
  { id: '3', text: 'Which courses have the highest dropout rates?', category: 'courses' },
  { id: '4', text: 'Identify at-risk students based on engagement', category: 'engagement' }
];

interface ChatContainerProps {
  className?: string;
  suggestions?: QuerySuggestion[];
}

export function ChatContainer({
  className = '',
  suggestions = DEFAULT_SUGGESTIONS
}: ChatContainerProps) {
  const {
    messages,
    isLoading,
    error,
    sendMessage,
    cancelQuery,
    clearMessages,
    statusMessage,
    thinkingSteps,
    isThinkingExpanded,
    toggleThinkingExpanded
  } = useChat();

  const handleSuggestionClick = (suggestion: QuerySuggestion) => {
    sendMessage(suggestion.text);
  };

  return (
    <div className={`flex flex-col h-full bg-white ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">
            Illuminate Intelligence
          </h1>
          <p className="text-sm text-gray-500">
            Ask questions about your educational data
          </p>
        </div>
        {messages.length > 0 && (
          <button
            onClick={clearMessages}
            className="px-3 py-1 text-sm text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-md transition-colors"
          >
            Clear Chat
          </button>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-hidden">
        {messages.length === 0 ? (
          <WelcomeScreen
            suggestions={suggestions}
            onSuggestionClick={handleSuggestionClick}
          />
        ) : (
          <MessageList messages={messages} />
        )}
      </div>

      {/* Thinking Bubble - shows agent's chain of thought */}
      {thinkingSteps.length > 0 && (
        <div className="px-4 py-2">
          <ThinkingBubble
            steps={thinkingSteps}
            isExpanded={isThinkingExpanded}
            onToggle={toggleThinkingExpanded}
            isLoading={isLoading}
          />
        </div>
      )}

      {/* Loading Indicator with streaming status */}
      {isLoading && thinkingSteps.length === 0 && (
        <div className="px-4 py-2">
          <TypingIndicator agentName={statusMessage || "Processing..."} />
        </div>
      )}

      {/* Cancel button - visible during loading */}
      {isLoading && (
        <div className="px-4 py-2 flex justify-center">
          <button
            onClick={cancelQuery}
            className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-red-600 hover:text-red-700 bg-red-50 hover:bg-red-100 border border-red-200 rounded-lg transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
            Stop generating
          </button>
        </div>
      )}

      {/* Error Display */}
      {error && !isLoading && (
        <div className="px-4 py-2">
          <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
            {error}
          </div>
        </div>
      )}

      {/* Input Area */}
      <div className="border-t border-gray-200">
        <InputArea
          onSubmit={sendMessage}
          disabled={isLoading}
          suggestions={messages.length === 0 ? [] : suggestions.slice(0, 2)}
        />
      </div>
    </div>
  );
}

interface WelcomeScreenProps {
  suggestions: QuerySuggestion[];
  onSuggestionClick: (suggestion: QuerySuggestion) => void;
}

function WelcomeScreen({ suggestions, onSuggestionClick }: WelcomeScreenProps) {
  return (
    <div className="flex flex-col items-center justify-center h-full p-8 text-center">
      <div className="w-16 h-16 bg-blue-100 rounded-full flex items-center justify-center mb-4">
        <svg
          className="w-8 h-8 text-blue-600"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"
          />
        </svg>
      </div>

      <h2 className="text-xl font-semibold text-gray-900 mb-2">
        Welcome to Illuminate Intelligence
      </h2>

      <p className="text-gray-600 mb-6 max-w-md">
        Ask natural language questions about your educational data.
        I can help you explore courses, grades, student information, and engagement metrics.
      </p>

      <div className="w-full max-w-lg">
        <p className="text-sm font-medium text-gray-700 mb-3">
          Try asking:
        </p>
        <div className="grid gap-2">
          {suggestions.map(suggestion => (
            <button
              key={suggestion.id}
              onClick={() => onSuggestionClick(suggestion)}
              className="w-full text-left px-4 py-3 bg-gray-50 hover:bg-gray-100 rounded-lg border border-gray-200 text-gray-700 text-sm transition-colors"
            >
              {suggestion.text}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export default ChatContainer;
