import { Cart } from "../src/cart";
import { Money } from "../src/util/money";

test("total", () => {
  const cart = new Cart();
  cart.add(new Money(100));
  expect(cart.total(0).cents).toBe(100);
});
