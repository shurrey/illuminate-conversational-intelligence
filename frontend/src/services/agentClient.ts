/**
 * Agent Client - A2A protocol client for frontend.
 *
 * Handles communication with the Orchestrator Agent.
 */

import type { Message, AgentResponse, Artifact, MessageRole, StreamingEvent } from '../types/message';
import { authService } from './authService';

export interface AgentClientConfig {
  baseUrl: string;
  apiKey?: string;
  timeout?: number;
}

const DEFAULT_CONFIG: AgentClientConfig = {
  baseUrl: import.meta.env.VITE_API_URL || 'http://localhost:8000',
  timeout: 180000  // 3 minutes - agents need time for Snowflake queries + validation
};

class AgentClient {
  private config: AgentClientConfig;

  constructor(config: Partial<AgentClientConfig> = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config };
  }

  private getAuthHeaders(): Record<string, string> {
    const token = this.config.apiKey || authService.getToken();
    if (token) {
      return { 'Authorization': `Bearer ${token}` };
    }
    return {};
  }

  /**
   * Send a message to the orchestrator agent.
   */
  async sendMessage(
    text: string,
    contextId?: string
  ): Promise<AgentResponse> {
    const messageId = crypto.randomUUID();

    const request = {
      jsonrpc: '2.0',
      method: 'message/send',
      params: {
        message: {
          role: 'user' as MessageRole,
          parts: [{ type: 'text', text }],
          messageId,
          contextId: contextId || crypto.randomUUID()
        }
      },
      id: messageId
    };

    try {
      const response = await fetch(`${this.config.baseUrl}/api/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...this.getAuthHeaders()
        },
        body: JSON.stringify(request),
        signal: AbortSignal.timeout(this.config.timeout!)
      });

      if (!response.ok) {
        throw new Error(`HTTP error: ${response.status}`);
      }

      const result = await response.json();

      // Handle JSON-RPC error format
      if (result.error) {
        throw new Error(result.error.message || 'Unknown error');
      }

      // Backend returns data directly (not wrapped in result.result)
      return this.parseResponse(result);
    } catch (error) {
      throw error;
    }
  }

  /**
   * Send a message and receive streaming response.
   *
   * Yields streaming events:
   * - type: "status" | "routing" | "thinking" | "complete" | "error"
   * - message: Status message (for status/thinking/error)
   * - data: Final response (for complete)
   * - agent: Agent name (for routing/thinking)
   *
   * @param text - The message text to send
   * @param contextId - Optional conversation context ID
   * @param signal - Optional AbortSignal to cancel the request
   * @param requestId - Optional request ID for cancellation support
   */
  async *sendMessageStreaming(
    text: string,
    contextId?: string,
    signal?: AbortSignal,
    requestId?: string
  ): AsyncGenerator<StreamingEvent> {
    const messageId = crypto.randomUUID();
    const reqId = requestId || messageId;

    const request = {
      jsonrpc: '2.0',
      method: 'message/stream',
      params: {
        message: {
          role: 'user' as MessageRole,
          parts: [{ type: 'text', text }],
          messageId,
          contextId: contextId || crypto.randomUUID()
        }
      },
      id: reqId,
      request_id: reqId  // For cancellation support
    };

    try {
      const response = await fetch(`${this.config.baseUrl}/api/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
          ...this.getAuthHeaders()
        },
        body: JSON.stringify(request),
        signal
      });

      if (!response.ok) {
        throw new Error(`HTTP error: ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error('No response body');
      }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = JSON.parse(line.slice(6));
            yield data;
          }
        }
      }
    } catch (error) {
      throw error;
    }
  }

  /**
   * Cancel an in-progress request on the backend.
   */
  async cancelRequest(requestId: string): Promise<boolean> {
    try {
      const response = await fetch(`${this.config.baseUrl}/api/chat/cancel/${requestId}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...this.getAuthHeaders()
        }
      });

      if (!response.ok) {
        console.error('Failed to cancel request:', response.status);
        return false;
      }

      const result = await response.json();
      return result.success === true;
    } catch (error) {
      console.error('Error cancelling request:', error);
      return false;
    }
  }

  /**
   * Get conversation history.
   */
  async getConversationHistory(contextId: string): Promise<Message[]> {
    try {
      const response = await fetch(
        `${this.config.baseUrl}/api/conversations/${contextId}`,
        {
          headers: {
            ...this.getAuthHeaders()
          }
        }
      );

      if (!response.ok) {
        throw new Error(`HTTP error: ${response.status}`);
      }

      return response.json();
    } catch {
      return [];
    }
  }

  private parseResponse(result: Record<string, unknown>): AgentResponse {
    return {
      text: (result.text as string) || '',
      artifacts: (result.artifacts as Artifact[]) || [],
      contextId: result.context_id as string | undefined,
      sources: result.sources as string[] | undefined,
      visualization: result.visualization as AgentResponse['visualization']
    };
  }

}

// Export singleton instance
export const agentClient = new AgentClient();

// Export class for custom configuration
export { AgentClient };
