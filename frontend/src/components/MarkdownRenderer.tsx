import React, { useState } from "react";
import { Check, Copy } from "lucide-react";

type InlineNode =
  | { type: "text"; value: string }
  | { type: "code"; value: string }
  | { type: "bold"; children: InlineNode[] }
  | { type: "italic"; children: InlineNode[] }
  | { type: "bold_italic"; children: InlineNode[] }
  | { type: "del"; children: InlineNode[] }
  | { type: "link"; text: string; url: string };

type Block =
  | { type: "heading"; level: number; content: InlineNode[] }
  | { type: "paragraph"; content: InlineNode[] }
  | { type: "code_block"; lang: string; code: string }
  | { type: "blockquote"; content: InlineNode[] }
  | { type: "unordered_list"; items: InlineNode[][] }
  | { type: "ordered_list"; items: InlineNode[][] }
  | { type: "table"; headers: InlineNode[][]; rows: InlineNode[][][] }
  | { type: "hr" };

export function parseInline(str: string): InlineNode[] {
  if (!str) return [];

  // Match inline tokens: code, bold_italic, bold, italic, del, links
  const regex =
    /(`[^`\n]+`|\*\*\*[^*\n]+?\*\*\*|\*\*[^*\n]+?\*\*|\*[^*\n]+?\*|((?:^|[\s(]))_([^_\s\n][^_\n]*?[^_\s\n]|[^_\s\n])_(?=[\s),.:;!?]|$)|~~[^~\n]+?~~|\[[^\]]+\]\([^)]+\))/g;

  const nodes: InlineNode[] = [];
  let lastIdx = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(str)) !== null) {
    if (match.index > lastIdx) {
      nodes.push({ type: "text", value: str.substring(lastIdx, match.index) });
    }

    const raw = match[0];
    if (raw.startsWith("`") && raw.endsWith("`")) {
      nodes.push({ type: "code", value: raw.slice(1, -1) });
    } else if (raw.startsWith("***") && raw.endsWith("***")) {
      nodes.push({ type: "bold_italic", children: parseInline(raw.slice(3, -3)) });
    } else if (raw.startsWith("**") && raw.endsWith("**")) {
      nodes.push({ type: "bold", children: parseInline(raw.slice(2, -2)) });
    } else if (raw.startsWith("*") && raw.endsWith("*")) {
      nodes.push({ type: "italic", children: parseInline(raw.slice(1, -1)) });
    } else if (match[3]) {
      // Underscore italic with preceding spacing/punctuation preserved
      if (match[2]) {
        nodes.push({ type: "text", value: match[2] });
      }
      nodes.push({ type: "italic", children: parseInline(match[3]) });
    } else if (raw.startsWith("~~") && raw.endsWith("~~")) {
      nodes.push({ type: "del", children: parseInline(raw.slice(2, -2)) });
    } else if (raw.startsWith("[") && raw.includes("](")) {
      const idx = raw.indexOf("](");
      const text = raw.slice(1, idx);
      const url = raw.slice(idx + 2, -1);
      nodes.push({ type: "link", text, url });
    }

    lastIdx = regex.lastIndex;
  }

  if (lastIdx < str.length) {
    nodes.push({ type: "text", value: str.substring(lastIdx) });
  }

  return nodes;
}

export function parseBlocks(markdown: string): Block[] {
  if (!markdown) return [];

  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;

  const isTableRow = (l: string) => {
    const t = l.trim();
    return t.startsWith("|") && t.includes("|", 1);
  };

  const splitTableRow = (l: string): string[] => {
    let t = l.trim();
    if (t.startsWith("|")) t = t.slice(1);
    if (t.endsWith("|")) t = t.slice(0, -1);
    return t.split("|").map((c) => c.trim());
  };

  while (i < lines.length) {
    const line = lines[i];

    // 1. Empty lines
    if (!line.trim()) {
      i++;
      continue;
    }

    // 2. Fenced code block
    const codeMatch = line.match(/^```([a-zA-Z0-9_-]*)/);
    if (codeMatch) {
      const lang = codeMatch[1] || "";
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      if (i < lines.length) i++; // consume closing ```
      blocks.push({ type: "code_block", lang, code: codeLines.join("\n") });
      continue;
    }

    // 3. Headings: # through ######
    const headingMatch = line.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      blocks.push({
        type: "heading",
        level: headingMatch[1].length,
        content: parseInline(headingMatch[2].trim()),
      });
      i++;
      continue;
    }

    // 4. Horizontal Rule
    if (/^(\*\*\*|---|___)\s*$/.test(line.trim())) {
      blocks.push({ type: "hr" });
      i++;
      continue;
    }

    // 5. Blockquote
    if (/^>\s?(.*)$/.test(line)) {
      const quoteLines: string[] = [];
      while (i < lines.length && /^>\s?(.*)$/.test(lines[i])) {
        quoteLines.push(lines[i].replace(/^>\s?/, ""));
        i++;
      }
      blocks.push({
        type: "blockquote",
        content: parseInline(quoteLines.join(" ")),
      });
      continue;
    }

    // 6. Tables
    if (
      isTableRow(line) &&
      i + 1 < lines.length &&
      /^\|?(\s*:?-+:?\s*\|)+\s*:?-+:?\s*\|?$/.test(lines[i + 1].trim())
    ) {
      const headers = splitTableRow(line);
      i += 2; // skip header and separator
      const rows: string[][] = [];
      while (i < lines.length && isTableRow(lines[i])) {
        rows.push(splitTableRow(lines[i]));
        i++;
      }
      blocks.push({
        type: "table",
        headers: headers.map((h) => parseInline(h)),
        rows: rows.map((r) => r.map((cell) => parseInline(cell))),
      });
      continue;
    }

    // 7. Unordered list
    if (/^\s*[-*+]\s+(.*)$/.test(line)) {
      const items: InlineNode[][] = [];
      while (i < lines.length && /^\s*[-*+]\s+(.*)$/.test(lines[i])) {
        const m = lines[i].match(/^\s*[-*+]\s+(.*)$/);
        if (m) {
          items.push(parseInline(m[1]));
        }
        i++;
      }
      blocks.push({ type: "unordered_list", items });
      continue;
    }

    // 8. Ordered list
    if (/^\s*\d+\.\s+(.*)$/.test(line)) {
      const items: InlineNode[][] = [];
      while (i < lines.length && /^\s*\d+\.\s+(.*)$/.test(lines[i])) {
        const m = lines[i].match(/^\s*\d+\.\s+(.*)$/);
        if (m) {
          items.push(parseInline(m[1]));
        }
        i++;
      }
      blocks.push({ type: "ordered_list", items });
      continue;
    }

    // 9. Regular Paragraph
    const paraLines: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !lines[i].trim().startsWith("```") &&
      !lines[i].match(/^#{1,6}\s+/) &&
      !lines[i].match(/^(\*\*\*|---|___)\s*$/) &&
      !lines[i].match(/^>\s?/) &&
      !lines[i].match(/^\s*[-*+]\s+/) &&
      !lines[i].match(/^\s*\d+\.\s+/) &&
      !isTableRow(lines[i])
    ) {
      paraLines.push(lines[i]);
      i++;
    }
    blocks.push({ type: "paragraph", content: parseInline(paraLines.join("\n")) });
  }

  return blocks;
}

function renderInlineNodes(nodes: InlineNode[], keyPrefix = "inline"): React.ReactNode[] {
  return nodes.map((node, i) => {
    const key = `${keyPrefix}-${i}`;
    switch (node.type) {
      case "text": {
        if (node.value.includes("\n")) {
          const parts = node.value.split("\n");
          return (
            <React.Fragment key={key}>
              {parts.map((p, pIdx) => (
                <React.Fragment key={`${key}-p-${pIdx}`}>
                  {p}
                  {pIdx < parts.length - 1 && <br />}
                </React.Fragment>
              ))}
            </React.Fragment>
          );
        }
        return <span key={key}>{node.value}</span>;
      }
      case "code":
        return (
          <code key={key} className="md-inline-code">
            {node.value}
          </code>
        );
      case "bold":
        return (
          <strong key={key} className="md-strong">
            {renderInlineNodes(node.children, `${key}-b`)}
          </strong>
        );
      case "italic":
        return (
          <em key={key} className="md-em">
            {renderInlineNodes(node.children, `${key}-i`)}
          </em>
        );
      case "bold_italic":
        return (
          <strong key={key} className="md-strong">
            <em className="md-em">{renderInlineNodes(node.children, `${key}-bi`)}</em>
          </strong>
        );
      case "del":
        return (
          <del key={key} className="md-del">
            {renderInlineNodes(node.children, `${key}-del`)}
          </del>
        );
      case "link":
        return (
          <a
            key={key}
            href={node.url}
            className="md-link"
            target="_blank"
            rel="noopener noreferrer"
          >
            {node.text}
          </a>
        );
      default:
        return null;
    }
  });
}

function CodeBlock({ code, lang }: { code: string; lang: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // fallback
    }
  };

  return (
    <div className="md-code-block">
      <div className="md-code-header">
        <span className="md-code-lang">{lang || "code"}</span>
        <button
          type="button"
          className="md-code-copy-btn"
          onClick={handleCopy}
          title="Copy code"
        >
          {copied ? (
            <>
              <Check size={11} className="text-cyan" />
              <span>Copied!</span>
            </>
          ) : (
            <>
              <Copy size={11} />
              <span>Copy</span>
            </>
          )}
        </button>
      </div>
      <pre className="md-code-content">
        <code>{code}</code>
      </pre>
    </div>
  );
}

interface MarkdownRendererProps {
  content?: string | null;
  className?: string;
  compact?: boolean;
}

export const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({
  content,
  className = "",
  compact = false,
}) => {
  if (!content || !content.trim()) {
    return null;
  }

  const blocks = parseBlocks(content);

  return (
    <div className={`md-container ${compact ? "md-compact" : ""} ${className}`}>
      {blocks.map((block, bIdx) => {
        const key = `block-${bIdx}`;

        switch (block.type) {
          case "heading": {
            const children = renderInlineNodes(block.content, key);
            switch (block.level) {
              case 1:
                return (
                  <h1 key={key} className="md-h1">
                    {children}
                  </h1>
                );
              case 2:
                return (
                  <h2 key={key} className="md-h2">
                    {children}
                  </h2>
                );
              case 3:
                return (
                  <h3 key={key} className="md-h3">
                    {children}
                  </h3>
                );
              case 4:
                return (
                  <h4 key={key} className="md-h4">
                    {children}
                  </h4>
                );
              case 5:
                return (
                  <h5 key={key} className="md-h5">
                    {children}
                  </h5>
                );
              case 6:
              default:
                return (
                  <h6 key={key} className="md-h6">
                    {children}
                  </h6>
                );
            }
          }

          case "paragraph":
            return (
              <p key={key} className="md-p">
                {renderInlineNodes(block.content, key)}
              </p>
            );

          case "code_block":
            return <CodeBlock key={key} code={block.code} lang={block.lang} />;

          case "blockquote":
            return (
              <blockquote key={key} className="md-blockquote">
                {renderInlineNodes(block.content, key)}
              </blockquote>
            );

          case "unordered_list":
            return (
              <ul key={key} className="md-ul">
                {block.items.map((item, iIdx) => (
                  <li key={`${key}-item-${iIdx}`} className="md-li">
                    {renderInlineNodes(item, `${key}-item-${iIdx}`)}
                  </li>
                ))}
              </ul>
            );

          case "ordered_list":
            return (
              <ol key={key} className="md-ol">
                {block.items.map((item, iIdx) => (
                  <li key={`${key}-item-${iIdx}`} className="md-li">
                    {renderInlineNodes(item, `${key}-item-${iIdx}`)}
                  </li>
                ))}
              </ol>
            );

          case "table":
            return (
              <div key={key} className="md-table-wrapper">
                <table className="md-table">
                  {block.headers.length > 0 && (
                    <thead>
                      <tr>
                        {block.headers.map((h, hIdx) => (
                          <th key={`${key}-th-${hIdx}`}>
                            {renderInlineNodes(h, `${key}-th-${hIdx}`)}
                          </th>
                        ))}
                      </tr>
                    </thead>
                  )}
                  <tbody>
                    {block.rows.map((row, rIdx) => (
                      <tr key={`${key}-tr-${rIdx}`}>
                        {row.map((cell, cIdx) => (
                          <td key={`${key}-td-${rIdx}-${cIdx}`}>
                            {renderInlineNodes(cell, `${key}-td-${rIdx}-${cIdx}`)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );

          case "hr":
            return <hr key={key} className="md-hr" />;

          default:
            return null;
        }
      })}
    </div>
  );
};

