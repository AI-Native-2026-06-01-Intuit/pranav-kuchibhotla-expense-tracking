// Narrow local shape: the AI SDK's ToolInvocation type uses `any` internally
// for args/result. We re-type with `unknown` here so the rest of the UI stays
// strict, and so we can defensively handle either `toolName` or older `name`
// shapes if the SDK ever evolves.
export interface ToolInvocationLike {
  state: 'partial-call' | 'call' | 'result';
  toolCallId?: string;
  toolName?: string;
  name?: string;
  args?: unknown;
  arguments?: unknown;
  result?: unknown;
}

interface Props {
  invocation: ToolInvocationLike;
}

const ToolCallCard = ({ invocation }: Props) => {
  const name = invocation.toolName ?? invocation.name ?? 'tool';
  const args = invocation.args ?? invocation.arguments;
  const hasArgs = args !== undefined;
  const isResult = invocation.state === 'result';

  return (
    <aside aria-label="tool-call" data-state={invocation.state}>
      <header>
        <strong>{name}</strong>
      </header>
      {hasArgs && (
        <pre aria-label="tool-args">{JSON.stringify(args, null, 2)}</pre>
      )}
      {isResult && (
        <pre data-testid="tool-result">
          {JSON.stringify(invocation.result, null, 2)}
        </pre>
      )}
    </aside>
  );
};

export default ToolCallCard;
