/**
 * TypingIndicator - Shows when agent is processing.
 */


interface TypingIndicatorProps {
  agentName?: string;
}

export function TypingIndicator({ agentName = 'Thinking...' }: TypingIndicatorProps) {
  return (
    <div className="flex items-center gap-3 px-4 py-2">
      <div className="flex gap-1">
        <span className="w-2 h-2 bg-blue-500 rounded-full animate-bounce [animation-delay:-0.3s]" />
        <span className="w-2 h-2 bg-blue-500 rounded-full animate-bounce [animation-delay:-0.15s]" />
        <span className="w-2 h-2 bg-blue-500 rounded-full animate-bounce" />
      </div>
      <span className="text-sm text-gray-500">{agentName}</span>
    </div>
  );
}

export default TypingIndicator;
