import 'package:acme/models/patient.dart';
import 'services/api.dart' as api;
import 'dart:async';

abstract class Shape {}

class Home extends Shape with Mixin implements Comparable<Home> {
  Future<void> load() async {
    final p = Patient.parse({'name': 'x', 'age': 3});
    print(describe(p));
    await api.fetch('/patients');
  }

  void _helper() {}
}

void main() {
  runApp(Home());
}
