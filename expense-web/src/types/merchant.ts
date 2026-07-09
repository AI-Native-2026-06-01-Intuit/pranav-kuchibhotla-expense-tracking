export interface MerchantLine {
  readonly id: string;
  readonly amount: string;
}

export interface Merchant {
  readonly id: string;
  readonly mccCode: string;
  readonly transactionCount: number;
  readonly totalSpend: string;
  readonly lines: ReadonlyArray<MerchantLine>;
}
