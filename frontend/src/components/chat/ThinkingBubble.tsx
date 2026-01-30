/**
 * ThinkingBubble - Collapsible display of agent's chain of thought.
 *
 * Shows thinking steps and tool calls in a collapsible bubble.
 * Expands while processing, collapses when complete.
 * Auto-scrolls to show latest content.
 */

import React, { useEffect, useRef } from 'react';
import type { ThinkingStep } from '../../types/message';

interface ThinkingBubbleProps {
  steps: ThinkingStep[];
  isExpanded: boolean;
  onToggle: () => void;
  isLoading: boolean;
}

export function ThinkingBubble({
  steps,
  isExpanded,
  onToggle,
  isLoading
}: ThinkingBubbleProps) {
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new steps arrive
  useEffect(() => {
    if (scrollContainerRef.current && isExpanded) {
      scrollContainerRef.current.scrollTop = scrollContainerRef.current.scrollHeight;
    }
  }, [steps, isExpanded]);

  if (steps.length === 0) {
    return null;
  }

  // Count tool calls
  const toolCallCount = steps.filter(s => s.type === 'tool_call').length;

  // Get current agent
  const currentAgent = steps[steps.length - 1]?.agent || 'Agent';
  const agentDisplayName = currentAgent.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase());

  return (
    <div className="mb-3">
      {/* Header - always visible */}
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-3 py-2 bg-gray-50 hover:bg-gray-100 rounded-lg border border-gray-200 text-sm text-gray-600 transition-colors"
      >
        {/* Expand/Collapse icon */}
        <svg
          className={`w-4 h-4 transition-transform ${isExpanded ? 'rotate-90' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M9 5l7 7-7 7"
          />
        </svg>

        {/* Brain icon */}
        <svg className="w-4 h-4 text-purple-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
        </svg>

        <span className="flex-1 text-left">
          {isLoading ? (
            <span className="flex items-center gap-2">
              <span>{agentDisplayName} Agent is thinking</span>
              <span className="inline-flex">
                <span className="animate-bounce" style={{ animationDelay: '0ms' }}>.</span>
                <span className="animate-bounce" style={{ animationDelay: '150ms' }}>.</span>
                <span className="animate-bounce" style={{ animationDelay: '300ms' }}>.</span>
              </span>
            </span>
          ) : (
            <span>
              {agentDisplayName} Agent reasoning
              {toolCallCount > 0 && ` (${toolCallCount} tool${toolCallCount > 1 ? 's' : ''} used)`}
            </span>
          )}
        </span>

        {/* Loading spinner when active */}
        {isLoading && (
          <svg className="w-4 h-4 animate-spin text-purple-500" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
          </svg>
        )}
      </button>

      {/* Collapsible content */}
      {isExpanded && (
        <div
          ref={scrollContainerRef}
          className="mt-2 pl-4 border-l-2 border-purple-200 space-y-2 max-h-64 overflow-y-auto"
        >
          {steps.map((step, index) => (
            <div key={index} className="text-sm">
              {step.type === 'thinking' ? (
                <div className="text-gray-600">
                  <div className="font-medium text-purple-600 text-xs mb-1">
                    {step.agent.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase())} Agent
                  </div>
                  <div className="whitespace-pre-wrap text-gray-700 bg-white p-2 rounded border border-gray-100">
                    {step.content || 'Thinking...'}
                  </div>
                </div>
              ) : step.type === 'tool_call' ? (
                <div className="flex items-center gap-2 text-blue-600 bg-blue-50 px-2 py-1 rounded">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  </svg>
                  <span className="font-mono text-xs">
                    Tool #{step.tool_id}: {step.tool}
                  </span>
                </div>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default ThinkingBubble;
