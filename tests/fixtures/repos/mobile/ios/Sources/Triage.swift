import Foundation

/// Scores a visit.
struct Triage: Codable, Equatable {
    var level: Int

    init(level: Int) {
        self.level = level
    }

    func isUrgent() -> Bool {
        if level > 3 { return true }
        return false
    }

    private func helper() {}
}

protocol Scorer {
    func score(_ t: Triage) -> Int
}

extension Triage {
    static func make() -> Triage {
        return Triage(level: 1)
    }
}

func run() {
    let t = Triage.make()
    print("level \(t.level) done")
}
