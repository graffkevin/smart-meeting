import SwiftUI

/// Status dot of the local AI (green, orange, red), its explanation on hover
struct AIStatusView: View {
    let ai: AIState
    let model: String?

    var body: some View {
        HStack(spacing: 4) {
            Circle()
                .fill(color)
                .frame(width: 8, height: 8)
            Text(model.map { String(localized: "IA - \($0)") } ?? String(localized: "IA"))
        }
        .help(ai.hint)
        .accessibilityElement(children: .combine)
        .accessibilityValue(ai.hint)
    }

    private var color: Color {
        switch ai.tone {
        case .ready: .green
        case .warning: .orange
        case .down: .red
        }
    }
}

/// Status of a meeting as a colored capsule
struct StatusBadge: View {
    let status: MeetingStatus

    var body: some View {
        Text(status.label)
            .font(.caption.weight(.medium))
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(color.opacity(0.15), in: Capsule())
            .foregroundStyle(color)
    }

    private var color: Color {
        switch status {
        case .recording: .red
        case .transcribing, .analyzing: .blue
        case .transcribed: .secondary
        case .done: .green
        case .error: .orange
        }
    }
}

/// A small capsule: tag, owner, deadline, technical topic
struct Chip: View {
    let text: String
    var color: Color = .secondary
    var onRemove: (() -> Void)?

    var body: some View {
        HStack(spacing: 4) {
            Text(text)
            if let onRemove {
                Button(action: onRemove) {
                    Image(systemName: "xmark")
                        .font(.caption2.weight(.bold))
                }
                .buttonStyle(.plain)
                .accessibilityLabel(String(localized: "Retirer \(text)"))
            }
        }
        .font(.caption)
        .padding(.horizontal, 8)
        .padding(.vertical, 3)
        .background(color.opacity(0.15), in: Capsule())
    }
}

/// Tags of a meeting: chips, a field to add one (Return), and the known tags in a menu
struct TagEditor: View {
    @Binding var tags: [String]
    var suggestions: [String] = []
    @State private var draft = ""

    var body: some View {
        FlowLayout(spacing: 6) {
            ForEach(tags, id: \.self) { tag in
                Chip(text: tag, color: .accentColor) { tags.removeAll { $0 == tag } }
            }
            // Placeholder, not label: in a Form the title would become a label
            TextField(text: $draft, prompt: Text("Ajouter un tag")) { Text("Ajouter un tag") }
                .labelsHidden()
                .textFieldStyle(.plain)
                .frame(minWidth: 140)
                .onSubmit(add)
            let others = suggestions.filter { !tags.contains($0) }
            if !others.isEmpty {
                Menu {
                    ForEach(others, id: \.self) { tag in
                        Button(tag) { tags.append(tag) }
                    }
                } label: {
                    Image(systemName: "tag")
                }
                .menuStyle(.borderlessButton)
                .menuIndicator(.hidden)
                .fixedSize()
                .help("Tags déjà utilisés")
            }
        }
    }

    private func add() {
        let tag = draft.trimmingCharacters(in: .whitespaces)
        if !tag.isEmpty, !tags.contains(tag) { tags.append(tag) }
        draft = ""
    }
}

/// Progress of a local AI task from its estimated duration (the server does not report progress):
/// never shown done before it is
struct EstimatedProgress: View {
    let label: String
    let estimate: Double
    let startedAt: Date

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            let elapsed = context.date.timeIntervalSince(startedAt)
            let remaining = estimate - elapsed
            ProgressView(value: min(0.95, max(0, elapsed / max(estimate, 1)))) {
                Text(label)
            } currentValueLabel: {
                Text(remaining > 5
                    ? String(localized: "Encore environ \(Self.time(remaining))")
                    : String(localized: "Presque terminé…"))
            }
        }
    }

    private static func time(_ seconds: Double) -> String {
        Duration.seconds(seconds.rounded()).formatted(.units(allowed: [.minutes, .seconds], width: .abbreviated))
    }
}

/// Lays its children out in rows, wrapping like text
struct FlowLayout: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let rows = rows(for: subviews, width: proposal.width ?? .infinity)
        let height = rows.map(\.height).reduce(0, +) + spacing * CGFloat(max(0, rows.count - 1))
        let width = rows.map(\.width).max() ?? 0
        return CGSize(width: proposal.width ?? width, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var y = bounds.minY
        for row in rows(for: subviews, width: bounds.width) {
            var x = bounds.minX
            for index in row.indices {
                let size = subviews[index].sizeThatFits(.unspecified)
                subviews[index].place(at: CGPoint(x: x, y: y + (row.height - size.height) / 2), proposal: ProposedViewSize(size))
                x += size.width + spacing
            }
            y += row.height + spacing
        }
    }

    private struct Row {
        var indices: [Int] = []
        var width: CGFloat = 0
        var height: CGFloat = 0
    }

    private func rows(for subviews: Subviews, width: CGFloat) -> [Row] {
        var rows: [Row] = [Row()]
        for index in subviews.indices {
            let size = subviews[index].sizeThatFits(.unspecified)
            if !rows[rows.count - 1].indices.isEmpty, rows[rows.count - 1].width + spacing + size.width > width {
                rows.append(Row())
            }
            var row = rows[rows.count - 1]
            row.width += (row.indices.isEmpty ? 0 : spacing) + size.width
            row.height = max(row.height, size.height)
            row.indices.append(index)
            rows[rows.count - 1] = row
        }
        return rows
    }
}

/// A titled block of the meeting page
struct Panel<Content: View>: View {
    let title: String
    var systemImage: String?
    @ViewBuilder var content: Content

    var body: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 10) {
                content
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(6)
        } label: {
            if let systemImage {
                Label(title, systemImage: systemImage).font(.headline)
            } else {
                Text(title).font(.headline)
            }
        }
    }
}

/// Text of the local AI: its Markdown (bold, lists) rendered, selectable
struct AIText: View {
    let text: String

    var body: some View {
        let options = AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        Text((try? AttributedString(markdown: text, options: options)) ?? AttributedString(text))
            .textSelection(.enabled)
            .fixedSize(horizontal: false, vertical: true)
    }
}

extension NSPasteboard {
    /// Replaces the clipboard with a text
    static func copy(_ text: String) {
        general.clearContents()
        general.setString(text, forType: .string)
    }
}
