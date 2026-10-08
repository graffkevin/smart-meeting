import Foundation

/// An error of the local server, with its message when it gave one (FastAPI `detail`)
enum APIError: LocalizedError {
    case unreachable
    case http(status: Int, detail: String?)

    var errorDescription: String? {
        switch self {
        case .unreachable: String(localized: "Smart Meeting ne répond pas.")
        case let .http(status, detail): detail ?? String(localized: "Erreur du serveur (\(status)).")
        }
    }
}

/// Client of the local server's HTTP API (same routes as the web interface)
struct APIClient: Sendable {
    let baseURL: URL

    /// The local AI can take minutes on a CPU (server timeout: SM_OLLAMA_TIMEOUT_S)
    static let aiTimeout: TimeInterval = 900

    private static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .custom { decoder in
            let text = try decoder.singleValueContainer().decode(String.self)
            guard let date = parseDate(text) else {
                throw DecodingError.dataCorrupted(.init(codingPath: decoder.codingPath, debugDescription: "Date \(text)"))
            }
            return date
        }
        return decoder
    }()

    private static let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return encoder
    }()

    /// ISO 8601 dates of the server, with or without fractions of a second; without a time zone,
    /// local time (like the web interface)
    static func parseDate(_ text: String) -> Date? {
        let withZone = ISO8601DateFormatter()
        if let date = withZone.date(from: text) { return date }
        withZone.formatOptions.insert(.withFractionalSeconds)
        if let date = withZone.date(from: text) { return date }
        let local = DateFormatter()
        local.locale = Locale(identifier: "en_US_POSIX")
        for format in ["yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd'T'HH:mm:ss.SSSSSS"] {
            local.dateFormat = format
            if let date = local.date(from: text) { return date }
        }
        return nil
    }

    static func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        try decoder.decode(type, from: data)
    }

    // MARK: Routes

    func health() async throws -> Health {
        try await get("api/health", timeout: 3)
    }

    func meetings(search: String = "") async throws -> [Meeting] {
        try await get("api/meetings", query: search.isEmpty ? [] : [URLQueryItem(name: "q", value: search)])
    }

    func meeting(_ id: Int) async throws -> MeetingDetail {
        try await get("api/meetings/\(id)")
    }

    func report(_ id: Int) async throws -> String {
        let (data, _) = try await send(request("GET", "api/meetings/\(id)/report.md"))
        return String(decoding: data, as: UTF8.self)
    }

    func tags() async throws -> [TagCount] {
        try await get("api/tags")
    }

    func recentQuestions() async throws -> [String] {
        try await get("api/questions/recent")
    }

    func preferences() async throws -> Preferences {
        try await get("api/preferences")
    }

    func savePreferences(_ preferences: Preferences) async throws -> Preferences {
        try await call("PUT", "api/preferences", body: preferences)
    }

    func audioDevices() async throws -> AudioDevices {
        try await get("api/audio/devices")
    }

    func startMeeting(_ request: StartMeetingRequest) async throws -> Meeting {
        try await call("POST", "api/meetings", body: request)
    }

    func stopMeeting(_ id: Int) async throws -> Meeting {
        try await call("POST", "api/meetings/\(id)/stop", body: Optional<String>.none)
    }

    func rename(_ id: Int, title: String) async throws -> Meeting {
        try await call("PATCH", "api/meetings/\(id)", body: ["title": title])
    }

    func setTags(_ id: Int, tags: [String]) async throws -> Meeting {
        try await call("PUT", "api/meetings/\(id)/tags", body: ["tags": tags])
    }

    func renameSpeaker(_ id: Int, old: String, new: String) async throws {
        _ = try await send(request("PUT", "api/meetings/\(id)/speakers", body: ["old": old, "new": new]))
    }

    func analyze(_ id: Int) async throws {
        _ = try await send(request("POST", "api/meetings/\(id)/analyze"))
    }

    func ask(_ id: Int, question: String) async throws -> AskAnswer {
        try await call("POST", "api/meetings/\(id)/ask", body: ["question": question], timeout: Self.aiTimeout)
    }

    func deleteAudio(_ id: Int) async throws {
        _ = try await send(request("DELETE", "api/meetings/\(id)/audio"))
    }

    func deleteMeeting(_ id: Int) async throws {
        _ = try await send(request("DELETE", "api/meetings/\(id)"))
    }

    func restartAI() async throws {
        _ = try await send(request("POST", "api/ai/restart"))
    }

    /// Sends a video or audio file to transcribe. The multipart body is written to a temporary file
    /// and streamed from it: recordings can weigh gigabytes.
    func importFile(_ file: URL, title: String, language: String) async throws -> Meeting {
        let boundary = "SmartMeeting-\(UUID().uuidString)"
        let body = FileManager.default.temporaryDirectory.appending(path: "\(boundary).upload")
        defer { try? FileManager.default.removeItem(at: body) }
        try Self.writeMultipart(to: body, boundary: boundary, file: file, fields: ["title": title, "language": language])
        var upload = request("POST", "api/meetings/import", timeout: Self.aiTimeout)
        upload.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        let (data, response) = try await URLSession.shared.upload(for: upload, fromFile: body)
        try Self.check(data, response)
        return try Self.decoder.decode(Meeting.self, from: data)
    }

    /// WebSocket address of a meeting's live events
    func eventsURL(_ id: Int) -> URL {
        var components = URLComponents(url: baseURL.appending(path: "api/meetings/\(id)/ws"), resolvingAgainstBaseURL: false)!
        components.scheme = "ws"
        return components.url!
    }

    // MARK: Plumbing

    private func get<T: Decodable>(_ path: String, query: [URLQueryItem] = [], timeout: TimeInterval = 30) async throws -> T {
        var request = request("GET", path, timeout: timeout)
        if !query.isEmpty { request.url = request.url?.appending(queryItems: query) }
        let (data, _) = try await send(request)
        return try Self.decoder.decode(T.self, from: data)
    }

    private func call<T: Decodable, Body: Encodable>(
        _ method: String, _ path: String, body: Body?, timeout: TimeInterval = 30
    ) async throws -> T {
        let (data, _) = try await send(request(method, path, body: body, timeout: timeout))
        return try Self.decoder.decode(T.self, from: data)
    }

    private func request(_ method: String, _ path: String, timeout: TimeInterval = 30) -> URLRequest {
        var request = URLRequest(url: baseURL.appending(path: path), timeoutInterval: timeout)
        request.httpMethod = method
        return request
    }

    private func request<Body: Encodable>(
        _ method: String, _ path: String, body: Body?, timeout: TimeInterval = 30
    ) -> URLRequest {
        var request = request(method, path, timeout: timeout)
        if let body {
            request.httpBody = try? Self.encoder.encode(body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        return request
    }

    private func send(_ request: URLRequest) async throws -> (Data, URLResponse) {
        let data: Data, response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch let error as URLError where [.cannotConnectToHost, .networkConnectionLost, .timedOut].contains(error.code) {
            throw APIError.unreachable
        }
        try Self.check(data, response)
        return (data, response)
    }

    private static func check(_ data: Data, _ response: URLResponse) throws {
        guard let http = response as? HTTPURLResponse, !(200 ..< 300).contains(http.statusCode) else { return }
        // FastAPI: {"detail": "message"} (or a list of validation errors)
        let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
        throw APIError.http(status: http.statusCode, detail: detail)
    }

    private static func writeMultipart(to target: URL, boundary: String, file: URL, fields: [String: String]) throws {
        FileManager.default.createFile(atPath: target.path, contents: nil)
        let out = try FileHandle(forWritingTo: target)
        defer { try? out.close() }
        for (name, value) in fields {
            out.write(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n".utf8))
        }
        let filename = file.lastPathComponent.replacingOccurrences(of: "\"", with: "")
        out.write(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\nContent-Type: application/octet-stream\r\n\r\n".utf8))
        let input = try FileHandle(forReadingFrom: file)
        defer { try? input.close() }
        while let chunk = try input.read(upToCount: 4 << 20), !chunk.isEmpty {
            out.write(chunk)
        }
        out.write(Data("\r\n--\(boundary)--\r\n".utf8))
    }
}
