import type { KeyboardEvent } from 'react';

interface ThresholdSliderProps {
  readonly value: number;
  readonly onChange: (next: number) => void;
}

const MIN = 0;
const MAX = 100;

const clamp = (n: number): number => Math.min(MAX, Math.max(MIN, n));

const ThresholdSlider = ({ value, onChange }: ThresholdSliderProps) => {
  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>): void => {
    let next: number | null = null;
    switch (e.key) {
      case 'ArrowRight':
      case 'ArrowUp':
        next = clamp(value + 1);
        break;
      case 'ArrowLeft':
      case 'ArrowDown':
        next = clamp(value - 1);
        break;
      case 'Home':
        next = MIN;
        break;
      case 'End':
        next = MAX;
        break;
      default:
        return;
    }
    e.preventDefault();
    onChange(next);
  };

  return (
    <label>
      Threshold
      <input
        type="range"
        min={MIN}
        max={MAX}
        step={1}
        value={value}
        aria-label="Threshold"
        onChange={(e) => { onChange(Number(e.currentTarget.value)); }}
        onKeyDown={handleKeyDown}
      />
    </label>
  );
};

export default ThresholdSlider;
