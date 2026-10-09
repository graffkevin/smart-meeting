import SwiftUI

/// Transcript as a conversation: my sentences on the right, the other participants on the left, each
/// speaker with their own color. Double-click a speaker to name them in the whole meeting
/// ("Intervenant 2" -> "Paul"; a name already used merges both). While recording, the sentences
/// being spoken follow in grey until their final transcription.
struct TranscriptView: View {
    let model: MeetingModel
    @State private var renaming: String?
    @State private var newName = ""

    private static let colors: [Color] = [.blue, .purple, .green, .orange, .pink, .teal, .brown]

    var body: some View {
        let segments = model.segments
        let live = model.meeting?.status == .recording
        let partials = live ? model.partials.values.sorted { $0.startS < $1.startS } : []
        VStack(spacing: 0) {
            HStack {
                Text("Transcription").font(.headline)
                Spacer()
                if !segments.isEmpty {
                    Button {
                        NSPasteboard.copy(model.transcriptText)
                    } label: {
                        Label("Copier toute la transcription", systemImage: "doc.on.doc")
                    }
                    .labelStyle(.iconOnly)
                    .buttonStyle(.borderless)
                    .help("Copier toute la transcription")
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            Divider()
            if model.detail == nil {  // not loaded yet: not "nothing said"
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if segments.isEmpty, partials.isEmpty {
                ContentUnavailableView {
                    Label(live ? "Smart Meeting écoute…" : "Aucune parole détectée.", systemImage: "waveform")
                } description: {
                    if live { Text("Les phrases apparaîtront ici au fil de la réunion.") }
                }
            } else {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 10) {
                            ForEach(Array(segments.enumerated()), id: \.offset) { _, segment in
                                bubble(segment)
                            }
                            ForEach(partials, id: \.source) { partial in
                                partialBubble(partial)
                            }
                            Color.clear.frame(height: 1).id("end")
                        }
                        .padding(14)
                    }
                    // Follows the conversation while recording
                    .onChange(of: segments.count) { if live { withAnimation { proxy.scrollTo("end") } } }
                    .onChange(of: partials) { if live { proxy.scrollTo("end") } }
                    .onAppear { proxy.scrollTo("end") }
                }
            }
        }
        .alert(
            "Nommer cet intervenant",
            isPresented: Binding(get: { renaming != nil }, set: { if !$0 { renaming = nil } }),
            presenting: renaming
        ) { old in
            TextField("Nom", text: $newName)
            Button("Renommer") { Task { await model.renameSpeaker(old, to: newName) } }
            Button("Annuler", role: .cancel) {}
        } message: { _ in
            Text("Dans toute la réunion. Un nom déjà utilisé fusionne les deux intervenants.")
        }
    }

    private func bubble(_ segment: Segment) -> some View {
        let mine = segment.source == .mic
        return VStack(alignment: mine ? .trailing : .leading, spacing: 3) {
            HStack(spacing: 6) {
                if let speaker = segment.speaker {
                    HStack(spacing: 4) {
                        Circle().fill(color(of: speaker)).frame(width: 7, height: 7)
                        Text(speaker).fontWeight(.medium)
                    }
                    .onTapGesture(count: 2) { rename(speaker) }
                    .contextMenu {
                        Button("Renommer « \(speaker) »…") { rename(speaker) }
                    }
                    .help("Double-cliquez pour nommer cet intervenant dans toute la réunion")
                }
                Text(model.time(segment.startS)).foregroundStyle(.secondary)
            }
            .font(.caption)
            Text(segment.text)
                .textSelection(.enabled)
                .padding(.horizontal, 10)
                .padding(.vertical, 7)
                .background(
                    mine ? AnyShapeStyle(Color.accentColor.opacity(0.18)) : AnyShapeStyle(.quaternary.opacity(0.6)),
                    in: RoundedRectangle(cornerRadius: 10)
                )
        }
        .frame(maxWidth: .infinity, alignment: mine ? .trailing : .leading)
        .padding(mine ? .leading : .trailing, 36)
    }

    private func partialBubble(_ partial: PartialText) -> some View {
        let mine = partial.source == .mic
        return VStack(alignment: mine ? .trailing : .leading, spacing: 3) {
            Text("\(partial.speaker) · \(model.time(partial.startS))")
                .font(.caption)
                .foregroundStyle(.secondary)
            Text("\(partial.text)…")
                .italic()
                .foregroundStyle(.secondary)
                .padding(.horizontal, 10)
                .padding(.vertical, 7)
                .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(.quaternary))
        }
        .frame(maxWidth: .infinity, alignment: mine ? .trailing : .leading)
        .padding(mine ? .leading : .trailing, 36)
    }

    /// A color per speaker, in order of first appearance
    private func color(of speaker: String) -> Color {
        var speakers: [String] = []
        for segment in model.segments {
            if let name = segment.speaker, !speakers.contains(name) { speakers.append(name) }
        }
        let index = speakers.firstIndex(of: speaker) ?? 0
        return Self.colors[index % Self.colors.count]
    }

    private func rename(_ speaker: String) {
        newName = speaker
        renaming = speaker
    }
}
