interface ThresholdReadoutProps {
  readonly value: number;
}

const ThresholdReadout = ({ value }: ThresholdReadoutProps) => {
  return <p role="status">Threshold: {value}%</p>;
};

export default ThresholdReadout;
