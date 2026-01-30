/**
 * useChat Hook - Chat state management with streaming support.
 *
 * Provides chat functionality including:
 * - Message sending and receiving
 * - Streaming response handling with status updates
 * - Thinking/tool call tracking for chain of thought display
 * - Conversation context management
 */

import { useState, useCallback, useRef } from 'react';
import { agentClient } from '../services/agentClient';
import type { Message, ChatState, ThinkingStep, AgentResponse } from '../types/message';

interface UseChatReturn extends ChatState {
  sendMessage: (text: string) => Promise<void>;
  cancelQuery: () => Promise<void>;
  clearMessages: () => void;
  retry: () => Promise<void>;
  statusMessage: string | null;
  thinkingSteps: ThinkingStep[];
  isThinkingExpanded: boolean;
  toggleThinkingExpanded: () => void;
}

export function useChat(initialContextId?: string): UseChatReturn {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [contextId, setContextId] = useState<string | null>(initialContextId || null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [thinkingSteps, setThinkingSteps] = useState<ThinkingStep[]>([]);
  const [isThinkingExpanded, setIsThinkingExpanded] = useState(true);

  const lastUserMessageRef = useRef<string>('');
  const abortControllerRef = useRef<AbortController | null>(null);
  const currentRequestIdRef = useRef<string | null>(null);
  const thinkingStepsRef = useRef<ThinkingStep[]>([]);

  const toggleThinkingExpanded = useCallback(() => {
    setIsThinkingExpanded(prev => !prev);
  }, []);

  const cancelQuery = useCallback(async () => {
    // Cancel on backend first
    if (currentRequestIdRef.current) {
      await agentClient.cancelRequest(currentRequestIdRef.current);
      currentRequestIdRef.current = null;
    }

    // Then abort the frontend fetch
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }

    setIsLoading(false);
    setStatusMessage(null);
    setThinkingSteps([]);  // Clear thinking steps
    thinkingStepsRef.current = [];
    setIsThinkingExpanded(false);  // Collapse thinking bubble

    // Update the assistant message to show it was cancelled
    setMessages(prev => {
      if (prev.length === 0) return prev;
      const lastMessage = prev[prev.length - 1];
      if (lastMessage.role === 'assistant') {
        const newMessages = [...prev];
        newMessages[newMessages.length - 1] = {
          ...lastMessage,
          parts: [{ type: 'text', content: '_Query cancelled by user._' }]
        };
        return newMessages;
      }
      return prev;
    });
  }, []);

  const addMessage = useCallback((message: Message) => {
    setMessages(prev => [...prev, message]);
  }, []);

  const updateLastMessage = useCallback((updates: Partial<Message>) => {
    setMessages(prev => {
      if (prev.length === 0) return prev;
      const newMessages = [...prev];
      newMessages[newMessages.length - 1] = {
        ...newMessages[newMessages.length - 1],
        ...updates
      };
      return newMessages;
    });
  }, []);

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || isLoading) return;

    // Create new abort controller and request ID for this request
    abortControllerRef.current = new AbortController();
    const requestId = crypto.randomUUID();
    currentRequestIdRef.current = requestId;

    lastUserMessageRef.current = text;
    setError(null);
    setIsLoading(true);
    setStatusMessage('Sending...');
    setThinkingSteps([]);  // Clear previous thinking steps
    thinkingStepsRef.current = [];  // Clear ref too
    setIsThinkingExpanded(true);  // Expand thinking for new query

    // Add user message
    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      parts: [{ type: 'text', content: text }],
      artifacts: [],
      timestamp: new Date().toISOString(),
      contextId: contextId || undefined
    };
    addMessage(userMessage);

    // Add placeholder assistant message
    const assistantMessageId = crypto.randomUUID();
    const placeholderMessage: Message = {
      id: assistantMessageId,
      role: 'assistant',
      parts: [{ type: 'text', content: '' }],
      artifacts: [],
      timestamp: new Date().toISOString(),
      contextId: contextId || undefined
    };
    addMessage(placeholderMessage);

    // Track current thinking block index per agent (for updating in place until tool call)
    const currentThinkingIndex: Record<string, number> = {};
    const accumulatedThinking: Record<string, string> = {};

    try {
      // Use streaming endpoint with abort signal and request ID
      const signal = abortControllerRef.current?.signal;
      for await (const event of agentClient.sendMessageStreaming(text, contextId || undefined, signal, requestId)) {
        // Handle different event types
        switch (event.type) {
          case 'status':
            setStatusMessage(event.message || 'Processing...');
            break;

          case 'thinking':
            // Accumulate thinking text for current block
            const thinkingAgent = event.agent || 'unknown';
            const thinkingContent = event.content || event.message || '';

            // Use accumulated text from event or build it ourselves
            if (event.accumulated) {
              accumulatedThinking[thinkingAgent] = event.accumulated;
            } else {
              accumulatedThinking[thinkingAgent] = (accumulatedThinking[thinkingAgent] || '') + thinkingContent;
            }

            // Update status with thinking indicator
            const agentDisplayName = thinkingAgent.replace('_', ' ');
            setStatusMessage(`${agentDisplayName} is thinking...`);

            // Update or add the current thinking block
            setThinkingSteps(prev => {
              const newStep: ThinkingStep = {
                type: 'thinking',
                agent: thinkingAgent,
                content: accumulatedThinking[thinkingAgent],
                timestamp: new Date().toISOString()
              };

              let updated: ThinkingStep[];
              // If we have a current thinking block for this agent, update it
              if (currentThinkingIndex[thinkingAgent] !== undefined) {
                updated = [...prev];
                updated[currentThinkingIndex[thinkingAgent]] = newStep;
              } else {
                // Start a new thinking block
                currentThinkingIndex[thinkingAgent] = prev.length;
                updated = [...prev, newStep];
              }
              thinkingStepsRef.current = updated;  // Keep ref in sync
              return updated;
            });
            break;

          case 'tool_call':
            // Add tool call step - this "commits" the current thinking block
            const toolAgent = event.agent || 'unknown';
            const toolName = event.tool || 'unknown';
            const toolId = event.tool_id || 0;

            setStatusMessage(`Using tool: ${toolName}`);

            // Clear the current thinking index so next thinking starts a new block
            delete currentThinkingIndex[toolAgent];
            accumulatedThinking[toolAgent] = '';

            setThinkingSteps(prev => {
              const updated = [
                ...prev,
                {
                  type: 'tool_call' as const,
                  agent: toolAgent,
                  tool: toolName,
                  tool_id: toolId,
                  timestamp: new Date().toISOString()
                }
              ];
              thinkingStepsRef.current = updated;  // Keep ref in sync
              return updated;
            });
            break;

          case 'routing':
            const routingAgent = (event.agent || 'learning').replace('_', ' ');
            setStatusMessage(`Routing to ${routingAgent} agent...`);
            break;

          case 'error':
            setError(event.message || 'An error occurred');
            setStatusMessage(null);
            break;

          case 'cancelled':
            // Backend confirmed cancellation
            setStatusMessage(null);
            updateLastMessage({
              parts: [{ type: 'text', content: '_Query cancelled by user._' }]
            });
            return;  // Exit the loop

          case 'complete':
            // Final response with data
            const data = (event.data || {}) as AgentResponse;

            // Update context ID if provided
            const newContextId = data.context_id || data.contextId;
            if (newContextId && !contextId) {
              setContextId(newContextId);
            }

            // Capture current thinking steps from ref (more reliable than state in async context)
            const finalThinkingSteps = [...thinkingStepsRef.current];

            // Update assistant message with final response AND thinking steps
            setMessages(prev => {
              if (prev.length === 0) return prev;
              const newMessages = [...prev];
              newMessages[newMessages.length - 1] = {
                ...newMessages[newMessages.length - 1],
                parts: [{ type: 'text', content: data.text || '' }],
                artifacts: data.artifacts || [],
                thinkingSteps: finalThinkingSteps.length > 0 ? finalThinkingSteps : undefined
              };
              return newMessages;
            });

            // Clear global thinking steps (now stored with message)
            setThinkingSteps([]);
            thinkingStepsRef.current = [];
            setIsThinkingExpanded(false);
            setStatusMessage(null);
            break;

          default:
            // Handle any other event types
            if (event.message) {
              setStatusMessage(event.message);
            }
        }
      }
    } catch (err) {
      // Check if this was an abort
      if (err instanceof Error && err.name === 'AbortError') {
        // Already handled in cancelQuery, just return
        return;
      }

      const errorMessage = err instanceof Error ? err.message : 'An error occurred';
      setError(errorMessage);
      setStatusMessage(null);

      // Update assistant message with error
      updateLastMessage({
        parts: [{ type: 'text', content: `Sorry, I encountered an error: ${errorMessage}` }],
        artifacts: [{
          id: crypto.randomUUID(),
          type: 'error',
          data: errorMessage,
          title: 'Error'
        }]
      });
    } finally {
      setIsLoading(false);
      setStatusMessage(null);
      abortControllerRef.current = null;
      currentRequestIdRef.current = null;
    }
  }, [contextId, isLoading, addMessage, updateLastMessage]);

  const clearMessages = useCallback(() => {
    setMessages([]);
    setError(null);
    setContextId(null);
    setThinkingSteps([]);
    thinkingStepsRef.current = [];
    setIsThinkingExpanded(true);
  }, []);

  const retry = useCallback(async () => {
    if (lastUserMessageRef.current) {
      // Remove last assistant message
      setMessages(prev => prev.slice(0, -1));
      // Resend
      await sendMessage(lastUserMessageRef.current);
    }
  }, [sendMessage]);

  return {
    messages,
    isLoading,
    error,
    contextId,
    sendMessage,
    cancelQuery,
    clearMessages,
    retry,
    statusMessage,
    thinkingSteps,
    isThinkingExpanded,
    toggleThinkingExpanded
  };
}

export default useChat;
