/** Money helpers. */
export class Money {
  constructor(public cents: number) {}
  scale(factor: number): Money {
    return new Money(Math.round(this.cents * factor));
  }
}

export function zero(): Money {
  return new Money(0);
}
