import { useState, useEffect } from 'react'
import ChatInterface from './components/ChatInterface'
import FileUpload from './components/FileUpload'
import GraphViewer from './components/GraphViewer'
import ProposalReviewer from './components/ProposalReviewer'
import { Scale, Database, Shield, Share2, FileText, ExternalLink, Columns, AlertTriangle, Settings2, Sliders, Layers } from 'lucide-react'
import client from './api/client'

function App() {
  const [dbStatus, setDbStatus] = useState<'connected' | 'disconnected'>('connected')
  const [documents, setDocuments] = useState<any[]>([])
  const [comparisonMode, setComparisonMode] = useState(false)
  const [critique, setCritique] = useState(false)
  const [engine, setEngine] = useState<'lightrag' | 'graphrag'>('lightrag')
  const [ragMode, setRagMode] = useState('hybrid')
  const [lightragMode, setLightragMode] = useState('hybrid')
  const [graphragMethod, setGraphragMethod] = useState('drift')
  const [topK, setTopK] = useState(5)
  const [communityLevel, setCommunityLevel] = useState(2)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [showGraph, setShowGraph] = useState(false)
  
  const fetchDocuments = async () => {
    try {
      const response = await client.get('/documents')
      setDocuments(response.data)
    } catch (error) {
      console.error('Failed to fetch documents:', error)
    }
  }

  useEffect(() => {
    fetchDocuments()
    // Poll for updates every 10 seconds if uploading
    const interval = setInterval(fetchDocuments, 10000)
    return () => clearInterval(interval)
  }, [])

  return (
    <div className="flex h-screen w-full bg-background overflow-hidden">
      {/* Sidebar */}
      <aside className="w-80 border-r bg-card p-6 flex flex-col gap-6">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-primary/10 rounded-lg">
            <Scale className="w-6 h-6 text-primary" />
          </div>
          <h1 className="text-xl font-bold tracking-tight text-foreground">Law Assistant</h1>
        </div>

        <div className="space-y-6 flex-1 overflow-y-auto pr-2 scrollbar-thin">
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">RAG Settings</h2>
              <button
                onClick={() => setShowAdvanced(!showAdvanced)}
                className="text-[10px] text-primary hover:underline flex items-center gap-1"
                title="Tuning Parameters"
              >
                <Sliders className="w-3 h-3" />
                {showAdvanced ? "Basic" : "Tune"}
              </button>
            </div>

            {/* Comparison Mode Toggle */}
            <button 
              onClick={() => setComparisonMode(!comparisonMode)}
              className={`w-full flex items-center justify-between p-3 rounded-xl border transition-all ${
                comparisonMode 
                  ? 'bg-primary/10 border-primary text-primary shadow-[0_0_12px_rgba(var(--primary),0.1)]' 
                  : 'bg-muted/50 border-border text-muted-foreground hover:bg-muted'
              }`}
            >
              <div className="flex items-center gap-2">
                <Columns className="w-4 h-4" />
                <span className="text-sm font-medium">Comparison Mode</span>
              </div>
              <div className={`w-8 h-4 rounded-full p-1 transition-colors ${comparisonMode ? 'bg-primary' : 'bg-muted-foreground/30'}`}>
                <div className={`w-2 h-2 rounded-full bg-white transition-transform ${comparisonMode ? 'translate-x-4' : 'translate-x-0'}`} />
              </div>
            </button>

            {/* If in Comparison Mode: Configure comparison targets */}
            {comparisonMode ? (
              <div className="p-3 rounded-xl border border-primary/20 bg-primary/[0.03] space-y-2.5 text-xs">
                <div className="text-[11px] font-semibold text-foreground flex items-center gap-1.5">
                  <Layers className="w-3.5 h-3.5 text-primary" />
                  <span>Comparing 3 RAG Models</span>
                </div>

                {/* LightRAG Target */}
                <div className="space-y-1">
                  <label className="text-[10px] text-muted-foreground uppercase font-bold">LightRAG Model</label>
                  <select
                    value={lightragMode}
                    onChange={(e) => setLightragMode(e.target.value)}
                    className="w-full text-xs bg-card border border-border rounded-lg p-1.5 focus:ring-1 focus:ring-primary text-foreground"
                  >
                    <option value="hybrid">Hybrid (Local + Global + Vector)</option>
                    <option value="local">Local (Entity Graph)</option>
                    <option value="global">Global (Communities)</option>
                    <option value="mix">Mix (Graph & Text)</option>
                  </select>
                </div>

                {/* GraphRAG Target */}
                <div className="space-y-1">
                  <label className="text-[10px] text-emerald-600 dark:text-emerald-400 uppercase font-bold">GraphRAG Method</label>
                  <select
                    value={graphragMethod}
                    onChange={(e) => setGraphragMethod(e.target.value)}
                    className="w-full text-xs bg-card border border-border rounded-lg p-1.5 focus:ring-1 focus:ring-emerald-500 text-foreground"
                  >
                    <option value="drift">DRIFT Search (Trajectory reasoning)</option>
                    <option value="local">Local Search (Entities & units)</option>
                    <option value="global">Global Search (Community Map-Reduce)</option>
                    <option value="basic">Basic Search (Text units)</option>
                  </select>
                </div>

                <p className="text-[10px] text-muted-foreground italic pt-1">
                  Baseline: Naive RAG (Vector) compares side-by-side with {lightragMode.toUpperCase()} & {graphragMethod.toUpperCase()}.
                </p>
              </div>
            ) : (
              /* Single Engine & Mode Controls */
              <div className="space-y-2.5">
                <div className="space-y-1">
                  <label className="text-[10px] text-muted-foreground uppercase font-bold">Engine</label>
                  <div className="grid grid-cols-2 gap-1.5 bg-muted/40 p-1 rounded-lg border">
                    <button
                      type="button"
                      onClick={() => {
                        setEngine('lightrag')
                        setRagMode('hybrid')
                      }}
                      className={`py-1 text-xs font-medium rounded-md transition-all ${
                        engine === 'lightrag' 
                          ? 'bg-primary text-primary-foreground shadow-sm' 
                          : 'text-muted-foreground hover:text-foreground'
                      }`}
                    >
                      LightRAG
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setEngine('graphrag')
                        setRagMode('drift')
                      }}
                      className={`py-1 text-xs font-medium rounded-md transition-all ${
                        engine === 'graphrag' 
                          ? 'bg-emerald-600 text-white shadow-sm' 
                          : 'text-muted-foreground hover:text-foreground'
                      }`}
                    >
                      GraphRAG
                    </button>
                  </div>
                </div>

                <div className="space-y-1">
                  <label className="text-[10px] text-muted-foreground uppercase font-bold">Retrieval Mode</label>
                  {engine === 'lightrag' ? (
                    <select
                      value={ragMode}
                      onChange={(e) => setRagMode(e.target.value)}
                      className="w-full text-xs bg-card border border-border rounded-lg p-2 focus:ring-1 focus:ring-primary text-foreground"
                    >
                      <option value="hybrid">Hybrid (Local + Global + Vector)</option>
                      <option value="local">Local (Entity Graph)</option>
                      <option value="global">Global (Communities)</option>
                      <option value="mix">Mix (Graph & Knowledge)</option>
                      <option value="naive">Naive (Vector Only)</option>
                    </select>
                  ) : (
                    <select
                      value={ragMode}
                      onChange={(e) => setRagMode(e.target.value)}
                      className="w-full text-xs bg-card border border-border rounded-lg p-2 focus:ring-1 focus:ring-emerald-500 text-foreground"
                    >
                      <option value="drift">DRIFT Search (Reasoning Trajectory)</option>
                      <option value="local">Local Search (Entities & Units)</option>
                      <option value="global">Global Search (Community Map-Reduce)</option>
                      <option value="basic">Basic Search (Text Units)</option>
                    </select>
                  )}
                </div>
              </div>
            )}

            {/* Advanced Tuning Parameters */}
            {showAdvanced && (
              <div className="p-2.5 rounded-xl border bg-muted/30 space-y-2 text-xs animate-in fade-in">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-muted-foreground">Top K Context:</span>
                  <select
                    value={topK}
                    onChange={(e) => setTopK(Number(e.target.value))}
                    className="text-[11px] bg-card border border-border rounded p-1 text-foreground"
                  >
                    <option value={3}>3 chunks</option>
                    <option value={5}>5 chunks</option>
                    <option value={10}>10 chunks</option>
                    <option value={20}>20 chunks</option>
                  </select>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-muted-foreground">Community Level:</span>
                  <select
                    value={communityLevel}
                    onChange={(e) => setCommunityLevel(Number(e.target.value))}
                    className="text-[11px] bg-card border border-border rounded p-1 text-foreground"
                  >
                    <option value={1}>Level 1 (Detailed)</option>
                    <option value={2}>Level 2 (Balanced)</option>
                    <option value={3}>Level 3 (Broad)</option>
                  </select>
                </div>
              </div>
            )}

            {/* Critique Mode Toggle */}
            <button 
              onClick={() => setCritique(!critique)}
              className={`w-full flex items-center justify-between p-3 rounded-xl border transition-all ${
                critique 
                  ? 'bg-primary/10 border-primary text-primary shadow-[0_0_12px_rgba(var(--primary),0.1)]' 
                  : 'bg-muted/50 border-border text-muted-foreground hover:bg-muted'
              }`}
            >
              <div className="flex items-center gap-2">
                <Share2 className="w-4 h-4" />
                <span className="text-sm font-medium">Critique Mode</span>
              </div>
              <div className={`w-8 h-4 rounded-full p-1 transition-colors ${critique ? 'bg-primary' : 'bg-muted-foreground/30'}`}>
                <div className={`w-2 h-2 rounded-full bg-white transition-transform ${critique ? 'translate-x-4' : 'translate-x-0'}`} />
              </div>
            </button>

            <p className="text-[10px] text-muted-foreground px-1">
              {critique ? "Reflexion active: multi-round verification." : "Direct streaming response active."}
            </p>
          </section>

          <section>
            <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">System Status</h2>
            <div className="flex items-center gap-2 text-sm font-medium">
              <div className={`w-3 h-3 rounded-full ${dbStatus === 'connected' ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]' : 'bg-red-500'}`} />
              <span className="text-foreground">DB: {dbStatus === 'connected' ? 'Connected' : 'Disconnected'}</span>
            </div>
          </section>

          <section>
            <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Knowledge Base</h2>
            <FileUpload onSuccess={fetchDocuments} />
          </section>

          <section>
            <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Graph Visualization</h2>
            <button 
              onClick={() => setShowGraph(true)}
              className="w-full flex items-center justify-between p-3 rounded-xl bg-primary/5 border border-primary/10 hover:bg-primary/10 transition-all group"
            >
              <div className="flex items-center gap-2">
                <Share2 className="w-4 h-4 text-primary" />
                <span className="text-sm font-medium text-foreground">Explore Graph</span>
              </div>
              <ExternalLink className="w-3 h-3 text-muted-foreground group-hover:text-primary transition-colors" />
            </button>
          </section>

          <section>
            <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3 flex items-center gap-1.5">
              <AlertTriangle className="w-3 h-3" />
              Conflict Review (HITL)
            </h2>
            <ProposalReviewer onUpdate={fetchDocuments} />
          </section>

          <section>
            <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3 flex justify-between">
              <span>Indexed Documents</span>
              <span className="text-[10px] lowercase text-muted-foreground font-normal">({documents.length})</span>
            </h2>
            <div className="space-y-2">
              {documents.length === 0 ? (
                <p className="text-xs text-muted-foreground italic px-1">No documents indexed yet.</p>
              ) : (
                documents.map((doc, idx) => (
                  <div key={idx} className="flex items-start gap-3 p-2 rounded-lg border bg-muted/30 hover:bg-muted/50 transition-all text-xs">
                    <FileText className="w-4 h-4 text-primary mt-0.5 flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="font-medium truncate text-foreground" title={doc.source}>{doc.source}</p>
                      <p className="text-[10px] text-muted-foreground capitalize">{doc.status}</p>
                    </div>
                  </div>
                ))
              )}
            </div>
          </section>
        </div>

        <div className="pt-6 border-t space-y-4">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Database className="w-4 h-4" />
            <span>Postgres + pgvector</span>
          </div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Shield className="w-4 h-4" />
            <span>DeepSeek V3.2 / Qwen 3</span>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 flex flex-col relative bg-muted/30">
        <ChatInterface 
          comparisonMode={comparisonMode} 
          critique={critique}
          engine={engine}
          ragMode={ragMode}
          lightragMode={lightragMode}
          graphragMethod={graphragMethod}
          topK={topK}
          communityLevel={communityLevel}
        />
      </main>
       {showGraph && <GraphViewer onClose={() => setShowGraph(false)} />}
    </div>
  )
}

export default App