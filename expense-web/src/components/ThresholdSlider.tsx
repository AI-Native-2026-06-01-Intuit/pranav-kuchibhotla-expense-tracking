import type { KeyboardEvent } from 'react';
import { useMerchantFilterStore } from '../stores/useMerchantFilterStore';

const MIN = 0;
const MAX = 100;

const clamp = (n: number): number => Math.min(MAX, Math.max(MIN, n));

const ThresholdSlider = () => {
  const value = useMerchantFilterStore((s) => s.threshold);
  const onChange = useMerchantFilterStore((s) => s.setThreshold);

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
