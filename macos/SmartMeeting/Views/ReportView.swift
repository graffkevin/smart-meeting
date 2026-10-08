import SwiftUI

/// Report of a meeting: summary, actions, decisions, open questions, risks and technical topics
struct ReportView: View {
    let analysis: MeetingAnalysis

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Panel(title: String(localized: "Résumé"), systemImage: "text.alignleft") {
                AIText(text: analysis.summary)
                    .font(.title3)
            }

            Panel(title: String(localized: "Actions"), systemImage: "checklist") {
                if analysis.actions.isEmpty {
                    nothing
                } else {
                    Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 10) {
                        GridRow {
                            Text("Action")
                            Text("Qui")
                            Text("Pour quand")
                        }
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                        Divider()
                        ForEach(Array(analysis.actions.enumerated()), id: \.offset) { _, action in
                            GridRow(alignment: .firstTextBaseline) {
                                HStack(alignment: .firstTextBaseline, spacing: 6) {
                                    Text(action.task).textSelection(.enabled)
                                    if action.verified == false {
                                        Image(systemName: "exclamationmark.triangle.fill")
                                            .foregroundStyle(.orange)
                                            .help("Introuvable mot pour mot dans la transcription : à vérifier")
                                    }
                                }
                                .gridColumnAlignment(.leading)
                                if let owner = action.owner {
                                    Chip(text: owner, color: .blue)
                                } else {
                                    Text("À définir").font(.caption).foregroundStyle(.secondary)
                                }
                                if let deadline = action.deadline {
                                    Chip(text: deadline, color: .purple)
                                } else {
                                    Text("Non fixée").font(.caption).foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                }
            }

            LazyVGrid(columns: [GridItem(.adaptive(minimum: 320), spacing: 16, alignment: .top)], spacing: 16) {
                list(String(localized: "Décisions"), analysis.decisions, icon: "checkmark.circle.fill", color: .green)
                list(String(localized: "Questions en suspens"), analysis.questions, icon: "questionmark.circle.fill", color: .blue)
                list(String(localized: "Points de vigilance"), analysis.risks, icon: "exclamationmark.triangle.fill", color: .orange)
                Panel(title: String(localized: "Sujets techniques")) {
                    if analysis.technicalTopics.isEmpty {
                        nothing
                    } else {
                        FlowLayout(spacing: 6) {
                            ForEach(analysis.technicalTopics, id: \.self) { Chip(text: $0) }
                        }
                    }
                }
            }
        }
    }

    private var nothing: some View {
        Text("Rien de particulier.").foregroundStyle(.secondary)
    }

    private func list(_ title: String, _ items: [String], icon: String, color: Color) -> some View {
        Panel(title: title) {
            if items.isEmpty {
                nothing
            } else {
                ForEach(items, id: \.self) { item in
                    Label {
                        Text(item).textSelection(.enabled)
                    } icon: {
                        Image(systemName: icon).foregroundStyle(color)
                    }
                }
            }
        }
    }
}
