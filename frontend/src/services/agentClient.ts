/**
 * Agent Client - A2A protocol client for frontend.
 *
 * Handles communication with the Orchestrator Agent.
 */

import type { Message, AgentResponse, Artifact, MessageRole, StreamingEvent } from '../types/message';

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
          ...(this.config.apiKey && { 'Authorization': `Bearer ${this.config.apiKey}` })
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
      // Only use mock response if explicitly enabled via VITE_MOCK_MODE
      // In development, errors should be shown to help debugging
      if (import.meta.env.VITE_MOCK_MODE === 'true') {
        console.warn('API error, falling back to mock response:', error);
        return this.getMockResponse(text);
      }
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
          ...(this.config.apiKey && { 'Authorization': `Bearer ${this.config.apiKey}` })
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
      // Only use mock response if explicitly enabled via VITE_MOCK_MODE
      if (import.meta.env.VITE_MOCK_MODE === 'true') {
        console.warn('API streaming error, falling back to mock response:', error);
        yield this.getMockResponse(text);
      } else {
        throw error;
      }
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
          ...(this.config.apiKey && { 'Authorization': `Bearer ${this.config.apiKey}` })
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
            ...(this.config.apiKey && { 'Authorization': `Bearer ${this.config.apiKey}` })
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

  private getMockResponse(query: string): AgentResponse {
    const queryLower = query.toLowerCase();

    // Mock responses based on query type
    if (queryLower.includes('grade') || queryLower.includes('gpa')) {
      return {
        text: 'Based on the data from Fall 2024, the average GPA across all courses is **3.42**. Here are the top performing courses by average grade:',
        artifacts: [{
          id: crypto.randomUUID(),
          type: 'table',
          data: {
            columns: ['Course', 'Department', 'Avg GPA', 'Students'],
            rows: [
              { Course: 'Introduction to Computer Science', Department: 'CS', 'Avg GPA': 3.7, Students: 150 },
              { Course: 'Data Structures', Department: 'CS', 'Avg GPA': 3.5, Students: 120 },
              { Course: 'English Composition', Department: 'English', 'Avg GPA': 3.4, Students: 180 },
              { Course: 'Calculus I', Department: 'Math', 'Avg GPA': 3.2, Students: 200 },
              { Course: 'Psychology 101', Department: 'Psychology', 'Avg GPA': 3.6, Students: 220 }
            ]
          },
          title: 'Course Performance - Fall 2024'
        }],
        visualization: {
          chart_type: 'bar',
          title: 'Average GPA by Course',
          x_axis: 'Course',
          y_axis: 'Avg GPA',
          data: [
            { Course: 'Intro to CS', 'Avg GPA': 3.7 },
            { Course: 'Data Structures', 'Avg GPA': 3.5 },
            { Course: 'English Comp', 'Avg GPA': 3.4 },
            { Course: 'Calculus I', 'Avg GPA': 3.2 },
            { Course: 'Psychology 101', 'Avg GPA': 3.6 }
          ]
        }
      };
    }

    if (queryLower.includes('enrollment') || queryLower.includes('student')) {
      return {
        text: 'Current enrollment data shows **870 active students** across all programs. The Computer Science program has the highest enrollment.',
        artifacts: [{
          id: crypto.randomUUID(),
          type: 'table',
          data: {
            columns: ['Program', 'Enrolled', 'Status'],
            rows: [
              { Program: 'Computer Science', Enrolled: 320, Status: 'Active' },
              { Program: 'Business Administration', Enrolled: 280, Status: 'Active' },
              { Program: 'Psychology', Enrolled: 170, Status: 'Active' },
              { Program: 'Engineering', Enrolled: 100, Status: 'Active' }
            ]
          },
          title: 'Enrollment by Program'
        }]
      };
    }

    if (queryLower.includes('risk') || queryLower.includes('warning') || queryLower.includes('at-risk')) {
      return {
        text: 'Early warning analysis identified **23 high-risk students** based on engagement patterns. These students have been inactive for more than 7 days or show declining activity trends.',
        artifacts: [{
          id: crypto.randomUUID(),
          type: 'table',
          data: {
            columns: ['Risk Level', 'Count', 'Action Required'],
            rows: [
              { 'Risk Level': 'High', Count: 23, 'Action Required': 'Immediate outreach' },
              { 'Risk Level': 'Medium', Count: 45, 'Action Required': 'Monitor closely' },
              { 'Risk Level': 'Low', Count: 802, 'Action Required': 'Standard support' }
            ]
          },
          title: 'Student Risk Assessment'
        }]
      };
    }

    // Default response
    return {
      text: 'I can help you explore educational data from Illuminate. Try asking about:\n\n- Course grades and GPA trends\n- Student enrollment patterns\n- Engagement and activity metrics\n- At-risk student identification\n\nWhat would you like to know?',
      artifacts: []
    };
  }
}

// Export singleton instance
export const agentClient = new AgentClient();

// Export class for custom configuration
export { AgentClient };
