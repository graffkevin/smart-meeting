import Foundation

// Types of the local server's API (backend/src/smart_meeting/models.py), decoded from snake_case.

enum MeetingStatus: String, Codable, CaseIterable {
    case recording, transcribing, transcribed, analyzing, done, error

    /// Statuses during which the meeting page listens to live events
    var isLive: Bool { [.recording, .transcribing, .analyzing].contains(self) }

    var label: String {
        switch self {
        case .recording: String(localized: "En cours")
        case .transcribing: String(localized: "Finalisation…")
        case .transcribed: String(localized: "Transcrite")
        case .analyzing: String(localized: "Compte rendu en cours…")
        case .done: String(localized: "Terminée")
        case .error: String(localized: "Erreur")
        }
    }
}

struct SetupStep: Codable, Hashable {
    var label: String
    var progress: Double?
    var error: String?
    var done: Bool
}

struct Health: Codable {
    var whisper: String
    var whisperDetail: String?
    var ollama: Bool
    var ollamaModel: String
    var ollamaModelAvailable: Bool
    var activeMeetingId: Int?
    var setup: [SetupStep]?
}

/// A meeting, as listed in the history (`actionCount`) or alone
struct Meeting: Codable, Identifiable, Hashable {
    var id: Int
    var title: String
    var status: MeetingStatus
    var startedAt: Date
    var endedAt: Date?
    var keepAudio: Bool?
    var summary: String?
    var error: String?
    var sourceFile: String?
    var language: String?
    var tags: [String]?
    var actionCount: Int?
}

/// Audio sources of a meeting: my microphone, and what the other participants say (the output)
enum AudioSource: String, Codable {
    case mic, remote
}

struct Segment: Codable, Hashable {
    var id: Int?
    var source: AudioSource
    var speaker: String?
    var startS: Double
    var endS: Double
    var text: String
}

struct ActionItem: Codable, Hashable {
    var task: String
    var owner: String?
    var deadline: String?
    var quote: String?
    var verified: Bool?
}

struct MeetingAnalysis: Codable, Hashable {
    var summary: String
    var decisions: [String]
    var actions: [ActionItem]
    var questions: [String]
    var risks: [String]
    var technicalTopics: [String]
}

struct AskAnswer: Codable, Hashable {
    var id: Int?
    var question: String
    var answer: String
}

struct AiEstimates: Codable, Hashable {
    var askS: Double
    var analysisS: Double
}

struct CapturedDevice: Codable, Hashable {
    var device: String?
    var auto: Bool
    var error: String?
    var permissionNeeded: Bool?
}

struct MeetingStorage: Codable, Hashable {
    var database: String
    var audio: String?
}

struct MeetingDetail: Codable {
    var meeting: Meeting
    var segments: [Segment]
    var analysis: MeetingAnalysis?
    var hasAudio: Bool
    var captured: [String: CapturedDevice]?
    var estimates: AiEstimates?
    var analysisElapsedS: Double?
    var questions: [AskAnswer]?
    var storage: MeetingStorage?
}

struct AudioDevice: Codable, Hashable {
    var name: String
    var description: String
    var isDefault: Bool
}

struct AudioDevices: Codable {
    var sources: [AudioDevice]
    var sinks: [AudioDevice]
    var inUseSource: String?
    var inUseSink: String?
}

struct Preferences: Codable, Equatable {
    var userName: String?
    var glossary: [String]?
    var language: String?
    var micDevice: String?
    var outputDevice: String?
    var keepAudio: Bool?
    var room: Bool?
    var uiLanguage: String?
    var aiMode: String?
}

struct TagCount: Codable, Hashable {
    var name: String
    var count: Int
}

struct StartMeetingRequest: Encodable {
    var title: String
    var micDevice: String?
    var remoteDevice: String?
    var keepAudio: Bool
    var language: String
    var tags: [String]
    var room: Bool
}

/// A message of the meeting WebSocket (backend `EventHub`): `type` says which fields are set
struct MeetingEvent: Decodable {
    var type: String
    var segment: Segment?
    var status: MeetingStatus?
    var levels: [String: Double]?
    var queue: Int?
    var devices: [String: CapturedDevice]?
    var doneS: Double?
    var totalS: Double?
    var source: AudioSource?
    var speaker: String?
    var startS: Double?
    var text: String?
}

/// Transcription languages offered ("auto": detected, sticky)
enum TranscriptionLanguage: String, CaseIterable, Identifiable {
    case auto, fr, en, de, es, it

    var id: String { rawValue }

    var label: String {
        switch self {
        case .auto: String(localized: "Automatique")
        case .fr: String(localized: "Français")
        case .en: String(localized: "Anglais")
        case .de: String(localized: "Allemand")
        case .es: String(localized: "Espagnol")
        case .it: String(localized: "Italien")
        }
    }
}
