import { Money, zero } from "../util/money";
import _ from "lodash";

/** A shopping cart. */
export class Cart {
  private lines: Money[] = [];
  add(m: Money): void {
    this.lines.push(m);
  }
  total(discount: number): Money {
    let sum = zero();
    for (const line of this.lines) {
      if (line.cents > 0 && discount >= 0) {
        sum = new Money(sum.cents + line.cents);
      }
    }
    return sum.scale(1 - discount);
  }
}

export const checkout = (cart: Cart): number => cart.total(Number(process.env.DISCOUNT ?? 0)).cents;
