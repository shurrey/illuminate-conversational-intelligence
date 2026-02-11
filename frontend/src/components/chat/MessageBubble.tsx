/**
 * MessageBubble - Individual message display component.
 *
 * Renders messages with:
 * - User/assistant styling
 * - Markdown content
 * - Embedded artifacts (tables, charts)
 * - Export functionality
 */

import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Message, Artifact, ThinkingStep } from '../../types/message';
import { ChartRenderer } from '../visualization/ChartRenderer';
import { DataTable } from '../visualization/DataTable';
import { ExportButton } from '../visualization/ExportButton';

/**
 * CodeBlock component with copy functionality
 */
function CodeBlock({ children, className }: { children: React.ReactNode; className?: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    // Extract text content from children
    const text = extractTextFromChildren(children);
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  return (
    <div className="relative group my-4">
      <pre className={`p-4 rounded-lg bg-gray-800 text-gray-100 overflow-x-auto text-sm ${className || ''}`}>
        {children}
      </pre>
      <button
        onClick={handleCopy}
        className="absolute top-2 right-2 px-2 py-1 text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 rounded opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1"
        title="Copy to clipboard"
      >
        {copied ? (
          <>
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
            Copied!
          </>
        ) : (
          <>
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
            </svg>
            Copy
          </>
        )}
      </button>
    </div>
  );
}

/**
 * Helper to extract text content from React children
 */
function extractTextFromChildren(children: React.ReactNode): string {
  if (typeof children === 'string') return children;
  if (typeof children === 'number') return String(children);
  if (Array.isArray(children)) {
    return children.map(extractTextFromChildren).join('');
  }
  if (React.isValidElement(children) && children.props?.children) {
    return extractTextFromChildren(children.props.children);
  }
  return '';
}

/**
 * Inline thinking display - collapsed brain icon that expands to show chain of thought
 */
function InlineThinking({ steps }: { steps: ThinkingStep[] }) {
  const [isExpanded, setIsExpanded] = useState(false);

  if (!steps || steps.length === 0) return null;

  const toolCallCount = steps.filter(s => s.type === 'tool_call').length;
  const currentAgent = steps[steps.length - 1]?.agent || 'Agent';
  const agentDisplayName = currentAgent.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase());

  return (
    <div className="mt-2 pt-2 border-t border-gray-200">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-700 transition-colors"
      >
        {/* Brain icon */}
        <svg className="w-3.5 h-3.5 text-purple-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
        </svg>
        <span>
          {agentDisplayName} reasoning
          {toolCallCount > 0 && ` · ${toolCallCount} tool${toolCallCount > 1 ? 's' : ''}`}
        </span>
        <svg
          className={`w-3 h-3 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {isExpanded && (
        <div className="mt-2 pl-3 border-l-2 border-purple-200 space-y-1.5 max-h-48 overflow-y-auto">
          {steps.map((step, index) => (
            <div key={index} className="text-xs">
              {step.type === 'thinking' ? (
                <div className="text-gray-600">
                  <div className="font-medium text-purple-600 text-[10px] mb-0.5">
                    {step.agent.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase())}
                  </div>
                  <div className="whitespace-pre-wrap text-gray-600 bg-gray-50 p-1.5 rounded text-[11px] leading-relaxed">
                    {step.content || 'Thinking...'}
                  </div>
                </div>
              ) : step.type === 'tool_call' ? (
                <div className="flex items-center gap-1.5 text-blue-600 bg-blue-50 px-1.5 py-0.5 rounded text-[11px]">
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  </svg>
                  <span className="font-mono">Tool #{step.tool_id}: {step.tool}</span>
                </div>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

interface MessageBubbleProps {
  message: Message;
  isLatest?: boolean;
}

export function MessageBubble({ message, isLatest: _isLatest = false }: MessageBubbleProps) {
  const isUser = message.role === 'user';

  // Extract text content
  const textContent = message.parts
    .filter(part => part.type === 'text')
    .map(part => part.content as string)
    .join('\n');

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[85%] ${
          isUser
            ? 'bg-blue-600 text-white rounded-2xl rounded-br-md'
            : 'bg-gray-100 text-gray-900 rounded-2xl rounded-bl-md'
        } px-4 py-3`}
      >
        {/* Message content */}
        <div className={`prose prose-sm max-w-none ${isUser ? 'prose-invert' : ''}`}>
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              // Headings with proper spacing
              h1: ({ children }) => (
                <h1 className="text-xl font-bold mt-6 mb-3 first:mt-0 text-gray-900">{children}</h1>
              ),
              h2: ({ children }) => (
                <h2 className="text-lg font-bold mt-5 mb-2 first:mt-0 text-gray-900">{children}</h2>
              ),
              h3: ({ children }) => (
                <h3 className="text-base font-semibold mt-4 mb-2 first:mt-0 text-gray-800">{children}</h3>
              ),
              h4: ({ children }) => (
                <h4 className="text-sm font-semibold mt-3 mb-1 first:mt-0 text-gray-800">{children}</h4>
              ),
              // Paragraphs with better spacing
              p: ({ children }) => (
                <p className="mb-3 last:mb-0 leading-relaxed">{children}</p>
              ),
              // Lists with better spacing
              ul: ({ children }) => (
                <ul className="list-disc pl-5 mb-4 space-y-1.5">{children}</ul>
              ),
              ol: ({ children }) => (
                <ol className="list-decimal pl-5 mb-4 space-y-1.5">{children}</ol>
              ),
              li: ({ children }) => (
                <li className="leading-relaxed">{children}</li>
              ),
              // Text styling
              strong: ({ children }) => (
                <strong className="font-semibold">{children}</strong>
              ),
              em: ({ children }) => (
                <em className="italic">{children}</em>
              ),
              // Blockquotes
              blockquote: ({ children }) => (
                <blockquote className="border-l-4 border-gray-300 pl-4 my-4 italic text-gray-600">
                  {children}
                </blockquote>
              ),
              // Horizontal rules
              hr: () => <hr className="my-6 border-gray-300" />,
              // Inline code
              code: ({ children, className }) => {
                // Check if this is a code block (has language class) vs inline code
                const isCodeBlock = className?.startsWith('language-');
                if (isCodeBlock) {
                  return (
                    <code className={`${className} text-sm font-mono`}>
                      {children}
                    </code>
                  );
                }
                // Inline code
                return (
                  <code className={`px-1.5 py-0.5 rounded font-mono text-sm ${isUser ? 'bg-blue-700' : 'bg-gray-200 text-gray-800'}`}>
                    {children}
                  </code>
                );
              },
              // Fenced code blocks with copy button
              pre: ({ children }) => (
                <CodeBlock>{children}</CodeBlock>
              ),
              // Table rendering with proper styling
              table: ({ children }) => (
                <div className="overflow-x-auto my-4 rounded-lg border border-gray-200 shadow-sm">
                  <table className="min-w-full divide-y divide-gray-200 text-sm">
                    {children}
                  </table>
                </div>
              ),
              thead: ({ children }) => (
                <thead className="bg-gray-50">
                  {children}
                </thead>
              ),
              tbody: ({ children }) => (
                <tbody className="bg-white divide-y divide-gray-200">
                  {children}
                </tbody>
              ),
              tr: ({ children }) => (
                <tr className="hover:bg-gray-50 transition-colors">
                  {children}
                </tr>
              ),
              th: ({ children }) => (
                <th className="px-4 py-2.5 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider whitespace-nowrap">
                  {children}
                </th>
              ),
              td: ({ children }) => (
                <td className="px-4 py-2.5 text-gray-700 whitespace-nowrap">
                  {children}
                </td>
              ),
              // Links
              a: ({ children, href }) => (
                <a href={href} className="text-blue-600 hover:underline" target="_blank" rel="noopener noreferrer">
                  {children}
                </a>
              )
            }}
          >
            {textContent}
          </ReactMarkdown>
        </div>

        {/* Artifacts */}
        {message.artifacts && message.artifacts.length > 0 && (
          <div className="mt-3 space-y-3">
            {message.artifacts.map(artifact => (
              <ArtifactRenderer key={artifact.id} artifact={artifact} />
            ))}

            {/* Export button for data artifacts */}
            {message.artifacts.some(a => a.type === 'table' || a.type === 'chart') && (
              <div className="pt-2">
                <ExportButton artifacts={message.artifacts} />
              </div>
            )}
          </div>
        )}

        {/* Timestamp */}
        <div
          className={`text-xs mt-2 ${
            isUser ? 'text-blue-200' : 'text-gray-400'
          }`}
        >
          {formatTimestamp(message.timestamp)}
        </div>

        {/* Inline thinking steps (for assistant messages) */}
        {!isUser && message.thinkingSteps && message.thinkingSteps.length > 0 && (
          <InlineThinking steps={message.thinkingSteps} />
        )}
      </div>
    </div>
  );
}

interface ArtifactRendererProps {
  artifact: Artifact;
}

function ArtifactRenderer({ artifact }: ArtifactRendererProps) {
  switch (artifact.type) {
    case 'table':
      return (
        <div className="bg-white rounded-lg overflow-hidden shadow-sm">
          {artifact.title && (
            <div className="px-3 py-2 bg-gray-50 border-b border-gray-200 font-medium text-sm text-gray-700">
              {artifact.title}
            </div>
          )}
          <DataTable data={artifact.data as { rows: Record<string, unknown>[]; columns: string[] }} />
        </div>
      );

    case 'chart':
      return (
        <div className="bg-white rounded-lg overflow-hidden shadow-sm">
          {artifact.title && (
            <div className="px-3 py-2 bg-gray-50 border-b border-gray-200 font-medium text-sm text-gray-700">
              {artifact.title}
            </div>
          )}
          <ChartRenderer config={artifact.data as import('../../types/message').ChartConfig} />
        </div>
      );

    case 'text':
      return (
        <div className="bg-white rounded-lg p-3 shadow-sm">
          {artifact.title && (
            <div className="font-medium text-sm text-gray-700 mb-2">
              {artifact.title}
            </div>
          )}
          <div className="text-sm text-gray-600">
            {artifact.data as string}
          </div>
        </div>
      );

    case 'error':
      return (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3">
          <div className="flex items-center gap-2 text-red-700">
            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
              <path
                fillRule="evenodd"
                d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z"
                clipRule="evenodd"
              />
            </svg>
            <span className="font-medium text-sm">Error</span>
          </div>
          <p className="mt-1 text-sm text-red-600">{artifact.data as string}</p>
        </div>
      );

    default:
      return null;
  }
}

function formatTimestamp(timestamp: string): string {
  const date = new Date(timestamp);
  const now = new Date();
  const diff = now.getTime() - date.getTime();

  // Less than 1 minute ago
  if (diff < 60000) {
    return 'Just now';
  }

  // Less than 1 hour ago
  if (diff < 3600000) {
    const minutes = Math.floor(diff / 60000);
    return `${minutes}m ago`;
  }

  // Today
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  // This week
  if (diff < 604800000) {
    return date.toLocaleDateString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' });
  }

  // Older
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

export default MessageBubble;
