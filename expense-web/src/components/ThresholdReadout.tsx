import { useMerchantFilterStore } from '../stores/useMerchantFilterStore';

const ThresholdReadout = () => {
  const threshold = useMerchantFilterStore((s) => s.threshold);
  return <p role="status">Threshold: {threshold}%</p>;
};

export default ThresholdReadout;
