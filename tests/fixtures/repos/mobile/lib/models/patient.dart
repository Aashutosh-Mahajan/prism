/// A patient record shown on the dashboard.
class Patient {
  final String name;
  final int age;

  Patient(this.name, this.age);

  /// Whether the patient is an adult.
  bool get isAdult => age >= 18;

  String label() {
    // TODO: localise
    return '${name} (${age})';
  }

  static Patient parse(Map<String, dynamic> json) {
    if (json['age'] == null) {
      throw ArgumentError('missing "age"');
    }
    return Patient(json['name'] as String, json['age'] as int);
  }
}

String describe(Patient p) => p.label();
