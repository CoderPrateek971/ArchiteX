import { useEffect, useMemo } from "react";
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  MarkerType,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
} from "reactflow";
import "reactflow/dist/style.css";

import ArchNode from "./ArchNode";
import type { GraphEdge, GraphNode } from "../lib/types";

const nodeTypes = {
  file: ArchNode,
  class: ArchNode,
  function: ArchNode,
  module: ArchNode,
  default: ArchNode,
};

type Props = {
  graphNodes: GraphNode[];
  graphEdges: GraphEdge[];
  selectedPath: string | null;
};

function FlowCanvas({ graphNodes, graphEdges, selectedPath }: Props) {
  const mappedNodes = useMemo<Node[]>(
    () =>
      graphNodes.map((node) => ({
        ...node,
        type: node.type && node.type in nodeTypes ? node.type : "default",
        data: {
          ...node.data,
          highlighted: Boolean(
            selectedPath &&
              (node.data.path === selectedPath ||
                node.data.label === selectedPath ||
                String(node.id).includes(selectedPath))
          ),
        },
      })),
    [graphNodes, selectedPath]
  );

  const mappedEdges = useMemo<Edge[]>(
    () =>
      graphEdges.map((edge) => {
        const kind = edge.data?.kind || "related";
        const isImport = kind === "import";
        return {
          ...edge,
          animated: isImport,
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: isImport ? "#22d3ee" : "#64748b",
          },
          style: {
            stroke: isImport ? "#22d3ee" : "#475569",
            strokeWidth: isImport ? 1.6 : 1.2,
          },
          labelStyle: { fill: "#94a3b8", fontSize: 10, fontFamily: "var(--font-mono)" },
          labelBgStyle: { fill: "#07090e", fillOpacity: 0.85 },
        };
      }),
    [graphEdges]
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(mappedNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(mappedEdges);

  useEffect(() => {
    setNodes(mappedNodes);
  }, [mappedNodes, setNodes]);

  useEffect(() => {
    setEdges(mappedEdges);
  }, [mappedEdges, setEdges]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      nodeTypes={nodeTypes}
      fitView
      fitViewOptions={{ padding: 0.2 }}
      minZoom={0.2}
      maxZoom={1.8}
      proOptions={{ hideAttribution: true }}
    >
      <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#1e293b" />
      <MiniMap
        pannable
        zoomable
        maskColor="rgba(5, 7, 12, 0.75)"
        nodeColor="#334155"
        style={{
          backgroundColor: "#0b0f19",
          border: "1px solid rgba(255, 255, 255, 0.1)",
          borderRadius: 10,
        }}
      />
      <Controls
        style={{
          border: "1px solid rgba(255, 255, 255, 0.1)",
          borderRadius: 8,
          overflow: "hidden",
        }}
      />
    </ReactFlow>
  );
}

export default function ArchitectureCanvas(props: Props) {
  return (
    <div style={{ height: "100%", width: "100%" }}>
      <ReactFlowProvider>
        <FlowCanvas {...props} />
      </ReactFlowProvider>
    </div>
  );
}
