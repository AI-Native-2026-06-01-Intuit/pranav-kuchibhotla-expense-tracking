interface ThresholdSliderProps {
  readonly value: number;
  readonly onChange: (next: number) => void;
}

const ThresholdSlider = ({ value, onChange }: ThresholdSliderProps) => {
  return (
    <label>
      Threshold
      <input
        type="range"
        min={0}
        max={100}
        value={value}
        aria-label="Threshold"
        onChange={(e) => { onChange(Number(e.currentTarget.value)); }}
      />
    </label>
  );
};

export default ThresholdSlider;
