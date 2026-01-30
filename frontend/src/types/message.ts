/**
 * Type definitions for chat messages and artifacts.
 */

export type MessageRole = 'user' | 'assistant' | 'system';

export type ArtifactType = 'table' | 'chart' | 'text' | 'error';

export type ChartType = 'bar' | 'line' | 'pie' | 'scatter' | 'heatmap' | 'histogram';

export interface ChartConfig {
  chart_type: ChartType;
  title: string;
  x_axis: string;
  y_axis: string;
  data: Record<string, unknown>[];
  x_label?: string;
  y_label?: string;
  color_by?: string;
}

export interface TableData {
  rows: Record<string, unknown>[];
  columns: string[];
}

export interface Artifact {
  id: string;
  type: ArtifactType;
  data: ChartConfig | TableData | string;
  title?: string;
  description?: string;
}

export interface MessagePart {
  type: 'text' | 'artifact';
  content: string | Record<string, unknown>;
}

export interface Message {
  id: string;
  role: MessageRole;
  parts: MessagePart[];
  artifacts: Artifact[];
  timestamp: string;
  contextId?: string;
  thinkingSteps?: ThinkingStep[];  // Chain of thought steps for this message
}

export interface Conversation {
  id: string;
  title: string;
  messages: Message[];
  createdAt: string;
  updatedAt: string;
}

export interface QuerySuggestion {
  id: string;
  text: string;
  category: 'courses' | 'grades' | 'students' | 'engagement';
}

export interface User {
  id: string;
  name: string;
  role: string;
  permissions: string[];
}

export interface ChatState {
  messages: Message[];
  isLoading: boolean;
  error: string | null;
  contextId: string | null;
}

export interface AgentResponse {
  text: string;
  artifacts: Artifact[];
  contextId?: string;
  context_id?: string;  // Backend uses snake_case
  sources?: string[];
  visualization?: ChartConfig;
}

export interface StreamingEvent {
  type: 'status' | 'routing' | 'thinking' | 'tool_call' | 'tool_result' | 'text' | 'complete' | 'error' | 'cancelled';
  message?: string;
  agent?: string;
  intent?: string;
  confidence?: number;
  data?: AgentResponse;
  context_id?: string;
  // Thinking event fields
  content?: string;        // Text chunk
  accumulated?: string;    // Full accumulated text so far
  // Tool call event fields
  tool?: string;           // Tool name
  tool_id?: number;        // Tool call sequence number
  input?: Record<string, unknown>;  // Tool input parameters
}

export interface ThinkingStep {
  type: 'thinking' | 'tool_call';
  agent: string;
  content?: string;        // For thinking: the text
  tool?: string;           // For tool_call: tool name
  tool_id?: number;        // For tool_call: sequence number
  timestamp: string;
}

export interface ThinkingState {
  steps: ThinkingStep[];
  isExpanded: boolean;
  currentAgent?: string;
}
