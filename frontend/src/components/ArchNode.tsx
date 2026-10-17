import React from "react";
import { Box, FileCode, Package, Workflow } from "lucide-react";
import { Handle, Position, type NodeProps } from "reactflow";
import type { GraphNodeData } from "../lib/types";

const KIND_CONFIG: Record<
  string,
  { icon: typeof FileCode; borderLeft: string; chipBg: string; chipColor: string }
> = {
  file: {
    icon: FileCode,
    borderLeft: "var(--cyan-400)",
    chipBg: "var(--cyan-bg)",
    chipColor: "var(--cyan-400)",
  },
  class: {
    icon: Box,
    borderLeft: "var(--violet-400)",
    chipBg: "var(--violet-bg)",
    chipColor: "var(--violet-400)",
  },
  function: {
    icon: Workflow,
    borderLeft: "var(--emerald-400)",
    chipBg: "var(--emerald-bg)",
    chipColor: "var(--emerald-400)",
  },
  module: {
    icon: Package,
    borderLeft: "var(--text-muted)",
    chipBg: "rgba(255, 255, 255, 0.08)",
    chipColor: "var(--text-secondary)",
  },
};

export default function ArchNode({ data, selected }: NodeProps<GraphNodeData>) {
  const kind = String(data.kind || "file").toLowerCase();
  const config = KIND_CONFIG[kind] || KIND_CONFIG.file;
  const Icon = config.icon;
  const isHighlighted = Boolean(data.highlighted);

  return (
    <div
      className={`arch-node ${selected ? "selected" : ""} ${isHighlighted ? "highlighted" : ""}`}
      style={{ borderLeftColor: config.borderLeft }}
    >
      <Handle
        type="target"
        position={Position.Left}
        style={{
          width: 8,
          height: 8,
          background: "var(--text-muted)",
          borderColor: "var(--bg-base)",
        }}
      />
      
      <div className="arch-node-content">
        <span
          className="arch-node-chip"
          style={{ background: config.chipBg, color: config.chipColor }}
        >
          <Icon size={14} />
        </span>
        <div className="arch-node-text">
          <p className="arch-node-title" title={data.label}>{data.label}</p>
          <p className="arch-node-kind">{kind}</p>
        </div>
      </div>

      <Handle
        type="source"
        position={Position.Right}
        style={{
          width: 8,
          height: 8,
          background: "var(--text-muted)",
          borderColor: "var(--bg-base)",
        }}
      />
    </div>
  );
}
