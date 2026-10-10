package com.acme

import com.acme.models.Patient
import kotlin.math.max

/** Computes a dose. */
data class Dose(val mg: Int) {
    fun scaled(factor: Double): Dose {
        val value = max(1, (mg * factor).toInt())
        return Dose(value)
    }

    private fun secret() = 42
}

interface Repo : Closeable {
    fun find(id: Int): Patient?
}

fun main() {
    println(Dose(5).scaled(2.0))
}

object Registry {
    suspend fun load(): List<Patient> = emptyList()
}
