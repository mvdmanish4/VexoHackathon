import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

struct MorseStep: Codable {
    let pattern: [Int]
    let gap: Int
}

struct MorseMessage: Codable {
    let text: String
    let steps: [MorseStep]
}

struct Turn: Decodable, Identifiable {
    let id: Int
    let kind: String?
    let original: MorseMessage
    let selected: MorseMessage
    let originalUnits: Int
    let selectedUnits: Int
    let status: String

    var savedPercent: Int {
        Int((100 * (1 - Double(selectedUnits) / Double(max(originalUnits, 1)))).rounded())
    }
}

struct Feed: Decodable {
    let session: String
    let latest: Int
    let missed: Bool
    let messages: [Turn]
}

struct ReceiverEndpoint {
    let root: URL
    let code: String

    init(address: String, code: String) throws {
        guard let url = URL(string: address.trimmingCharacters(in: .whitespacesAndNewlines)),
              let scheme = url.scheme, ["http", "https"].contains(scheme),
              url.host != nil, url.user == nil, url.password == nil,
              ["/", ""].contains(url.path), url.query == nil, url.fragment == nil else {
            throw FeedError.invalidAddress
        }
        root = url
        self.code = code.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    func fetch(after: Int, session: String) async throws -> Feed {
        var components = URLComponents(url: root.appendingPathComponent("transcripts"), resolvingAgainstBaseURL: false)!
        components.queryItems = [URLQueryItem(name: "after", value: String(after)),
                                 URLQueryItem(name: "session", value: session)]
        var request = URLRequest(url: components.url!, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 4)
        request.setValue(code, forHTTPHeaderField: "X-Vexo-Code")
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw FeedError.unavailable }
        if http.statusCode == 401 { throw FeedError.wrongCode }
        guard http.statusCode == 200 else { throw FeedError.unavailable }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(Feed.self, from: data)
    }
}

enum FeedError: LocalizedError {
    case invalidAddress, wrongCode, unavailable

    var errorDescription: String? {
        switch self {
        case .invalidAddress: return "Enter the full receiver address from the Mac."
        case .wrongCode: return "Enter the receiver code shown on the Mac."
        case .unavailable: return "Could not reach the transcript feed."
        }
    }
}
