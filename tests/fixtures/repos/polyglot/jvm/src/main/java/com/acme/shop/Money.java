package com.acme.shop;

/** Money in cents. */
public class Money {
    private final long cents;

    public Money(long cents) { this.cents = cents; }

    public Money plus(Money other) { return new Money(cents + other.cents); }
}
