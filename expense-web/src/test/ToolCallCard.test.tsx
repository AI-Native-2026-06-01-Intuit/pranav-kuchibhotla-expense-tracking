import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import ToolCallCard, {
  type ToolInvocationLike,
} from '../pages/ToolCallCard';

const partial: ToolInvocationLike = {
  state: 'partial-call',
  toolCallId: 'call-1',
  toolName: 'lookupMerchant',
  args: { id: 'partial' },
};

const inFlight: ToolInvocationLike = {
  state: 'call',
  toolCallId: 'call-2',
  toolName: 'lookupMerchant',
  args: { id: 'stub-id-1' },
};

const finished: ToolInvocationLike = {
  state: 'result',
  toolCallId: 'call-3',
  toolName: 'lookupMerchant',
  args: { id: 'stub-id-1' },
  result: { id: 'stub-id-1', name: 'stub merchant' },
};

const legacyShape: ToolInvocationLike = {
  state: 'call',
  toolCallId: 'call-4',
  name: 'legacyTool',
  arguments: { foo: 'bar' },
};

describe('ToolCallCard', () => {
  it('renders aside with data-state="partial-call" and the tool name', () => {
    render(<ToolCallCard invocation={partial} />);
    const aside = screen.getByLabelText('tool-call');
    expect(aside).toHaveAttribute('data-state', 'partial-call');
    expect(aside).toHaveTextContent('lookupMerchant');
  });

  it('renders args JSON and no tool-result when state is "call"', () => {
    render(<ToolCallCard invocation={inFlight} />);
    const aside = screen.getByLabelText('tool-call');
    expect(aside).toHaveAttribute('data-state', 'call');
    expect(screen.getByLabelText('tool-args')).toHaveTextContent(
      '"id": "stub-id-1"',
    );
    expect(screen.queryByTestId('tool-result')).not.toBeInTheDocument();
  });

  it('renders data-testid="tool-result" with serialized payload when state is "result"', () => {
    render(<ToolCallCard invocation={finished} />);
    const aside = screen.getByLabelText('tool-call');
    expect(aside).toHaveAttribute('data-state', 'result');
    const result = screen.getByTestId('tool-result');
    expect(result).toHaveTextContent('"name": "stub merchant"');
    expect(result).toHaveTextContent('"id": "stub-id-1"');
  });

  it('falls back to legacy name/arguments fields when toolName/args are absent', () => {
    render(<ToolCallCard invocation={legacyShape} />);
    const aside = screen.getByLabelText('tool-call');
    expect(aside).toHaveTextContent('legacyTool');
    expect(screen.getByLabelText('tool-args')).toHaveTextContent('"foo": "bar"');
  });
});
