package com.acme.shop;

import java.util.ArrayList;
import java.util.List;

/** A cart of priced lines. */
public class Cart {
    private final List<Money> lines = new ArrayList<>();

    public void add(Money m) { lines.add(m); }

    public Money total() {
        Money sum = new Money(0);
        for (Money m : lines) {
            sum = sum.plus(m);
        }
        return sum;
    }

    public static void main(String[] args) {
        Cart cart = new Cart();
        cart.add(new Money(5));
        System.out.println(cart.total());
    }
}
