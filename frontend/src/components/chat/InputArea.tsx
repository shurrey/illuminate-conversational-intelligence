/**
 * InputArea - User input component with suggestions.
 *
 * Features:
 * - Auto-expanding textarea
 * - Submit on Enter (Shift+Enter for newline)
 * - Quick suggestion chips
 * - Disabled state during loading
 */

import React, { useState, useRef, useEffect, KeyboardEvent } from 'react';
import type { QuerySuggestion } from '../../types/message';

interface InputAreaProps {
  onSubmit: (text: string) => void;
  disabled?: boolean;
  suggestions?: QuerySuggestion[];
  placeholder?: string;
}

export function InputArea({
  onSubmit,
  disabled = false,
  suggestions = [],
  placeholder = 'Ask about your educational data...'
}: InputAreaProps) {
  const [input, setInput] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
    }
  }, [input]);

  // Focus textarea on mount
  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  const handleSubmit = () => {
    if (input.trim() && !disabled) {
      onSubmit(input.trim());
      setInput('');
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleSuggestionClick = (suggestion: QuerySuggestion) => {
    if (!disabled) {
      onSubmit(suggestion.text);
    }
  };

  return (
    <div className="p-4 space-y-3">
      {/* Quick suggestions */}
      {suggestions.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {suggestions.map(suggestion => (
            <button
              key={suggestion.id}
              onClick={() => handleSuggestionClick(suggestion)}
              disabled={disabled}
              className="px-3 py-1.5 text-xs bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-full transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {suggestion.text}
            </button>
          ))}
        </div>
      )}

      {/* Input area */}
      <div className="flex items-end gap-2">
        <div className="flex-1 relative">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={disabled}
            placeholder={placeholder}
            rows={1}
            className="w-full resize-none rounded-xl border border-gray-300 px-4 py-3 pr-12 text-gray-900 placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:bg-gray-50 disabled:cursor-not-allowed"
          />
          <button
            onClick={handleSubmit}
            disabled={disabled || !input.trim()}
            className="absolute right-2 bottom-2 p-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors disabled:bg-gray-300 disabled:cursor-not-allowed"
            aria-label="Send message"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
              />
            </svg>
          </button>
        </div>
      </div>

      {/* Help text */}
      <p className="text-xs text-gray-400 text-center">
        Press Enter to send, Shift+Enter for new line
      </p>
    </div>
  );
}

export default InputArea;
