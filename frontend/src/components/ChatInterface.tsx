import { useState, useRef, useEffect } from 'react'
import { Send, User, Bot, Loader2 } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import ReferenceCard from './ReferenceCard'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content?: string
  sources?: any[]
  comparison?: {
    naive: { content: string; sources: any[] }
    hybrid: { content: string; sources: any[] }
    drift: { content: string; sources: any[] }
  }
}

interface ChatInterfaceProps {
  comparisonMode: boolean
  critique: boolean
  engine?: 'lightrag' | 'graphrag'
  ragMode?: string
  lightragMode?: string
  graphragMethod?: string
  topK?: number
  communityLevel?: number
}

export default function ChatInterface({ 
  comparisonMode, 
  critique,
  engine = 'lightrag',
  ragMode = 'hybrid',
  lightragMode = 'hybrid',
  graphragMethod = 'drift',
  topK = 5,
  communityLevel = 2,
}: ChatInterfaceProps) {
  const [messages, setMessages] = useState<Message[]>([
    { id: 'initial', role: 'assistant', content: 'Hello! I am your Labour Law Assistant. How can I help you today?' }
  ])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  const handleSend = async () => {
    if (!input.trim() || isLoading) return

    const timestamp = Date.now().toString()
    const userMsgId = `${timestamp}-user`
    const assistantMsgId = `${timestamp}-assistant`
    
    const userMessage: Message = { id: userMsgId, role: 'user', content: input }
    setMessages(prev => [...prev, userMessage])
    setInput('')
    setIsLoading(true)

    // Placeholder for assistant message
    const assistantMessage: Message = { 
      id: assistantMsgId,
      role: 'assistant',
      content: '', 
      comparison: comparisonMode ? { 
        naive: { content: '', sources: [] }, 
        hybrid: { content: '', sources: [] },
        drift: { content: '', sources: [] }
      } : undefined
    }
    
    setMessages(prev => [...prev, assistantMessage])

    try {
      const response = await fetch(`${(import.meta as any).env.VITE_API_BASE_URL || 'http://localhost:8000/api'}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          message: input,
          comparison_mode: comparisonMode,
          critique,
          engine,
          rag_mode: ragMode,
          lightrag_mode: lightragMode,
          graphrag_method: graphragMethod,
          top_k: topK,
          community_level: communityLevel
        })
      })

      if (!response.ok) throw new Error('Network response was not ok')

      if (critique) {
        const data = await response.json()
        setMessages(prev => prev.map(msg => {
          if (msg.id !== assistantMsgId) return msg

          if (comparisonMode && data.naive && data.hybrid && data.drift) {
            return {
              ...msg,
              comparison: {
                naive: { content: data.naive.response, sources: data.naive.sources ?? [] },
                hybrid: { content: data.hybrid.response, sources: data.hybrid.sources ?? [] },
                drift: { content: data.drift.response, sources: data.drift.sources ?? [] }
              }
            }
          }

          return {
            ...msg,
            content: data.response,
            sources: data.sources ?? []
          }
        }))
      } else {
        const reader = response.body?.getReader()
        if (!reader) throw new Error('No reader available')

        const decoder = new TextDecoder()
        let readerBuffer = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          readerBuffer += decoder.decode(value, { stream: true })
          const lines = readerBuffer.split('\n')
          readerBuffer = lines.pop() || ''
          
          for (const line of lines) {
            const trimmedLine = line.trim()
            if (!trimmedLine || !trimmedLine.startsWith('data: ')) continue
            
            try {
              const data = JSON.parse(trimmedLine.slice(6))
              
              if (data.type === 'chunk') {
                setMessages(prev => prev.map(msg => {
                  if (msg.id !== assistantMsgId) return msg
                  
                  const newMsg = { ...msg }
                  if (newMsg.comparison) {
                    if (data.mode === 'naive') {
                      newMsg.comparison = {
                        ...newMsg.comparison,
                        naive: { ...newMsg.comparison.naive, content: newMsg.comparison.naive.content + data.content }
                      }
                    } else if (data.mode === 'drift') {
                      newMsg.comparison = {
                        ...newMsg.comparison,
                        drift: { ...newMsg.comparison.drift, content: newMsg.comparison.drift.content + data.content }
                      }
                    } else {
                      newMsg.comparison = {
                        ...newMsg.comparison,
                        hybrid: { ...newMsg.comparison.hybrid, content: newMsg.comparison.hybrid.content + data.content }
                      }
                    }
                  } else {
                    newMsg.content = (newMsg.content || '') + data.content
                  }
                  return newMsg
                }))
              } else if (data.type === 'error') {
                throw new Error(data.message)
              }
            } catch (e) {
              // Ignore parsing errors for non-JSON lines if any
            }
          }
        }
      }
    } catch (error) {
      setMessages(prev => prev.map(msg => 
        msg.id === assistantMsgId 
          ? { ...msg, content: 'Sorry, I encountered an error processing your request.' } 
          : msg
      ))
    } finally {
      setIsLoading(false)
    }
  }

  const MarkdownContent = ({ content, role }: { content: string, role: 'user' | 'assistant' }) => (
    <div className={`prose prose-sm max-w-none ${
      role === 'user' ? 'text-white' : 'text-slate-900 dark:text-slate-100'
    }`}>
      <ReactMarkdown 
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({node, ...props}) => <p className="leading-relaxed mb-3 last:mb-0 text-slate-800 dark:text-slate-200 text-sm font-normal" {...props} />,
          ul: ({node, ...props}) => <ul className="list-disc ml-5 mb-3 text-slate-800 dark:text-slate-200 text-sm" {...props} />,
          ol: ({node, ...props}) => <ol className="list-decimal ml-5 mb-3 text-slate-800 dark:text-slate-200 text-sm" {...props} />,
          li: ({node, ...props}) => <li className="mb-1 leading-relaxed" {...props} />,
          h1: ({node, ...props}) => <h1 className="text-lg font-bold mb-3 mt-4 text-slate-950 dark:text-white" {...props} />,
          h2: ({node, ...props}) => <h2 className="text-base font-bold mb-2.5 mt-3 text-slate-950 dark:text-white" {...props} />,
          h3: ({node, ...props}) => <h3 className="text-sm font-bold mb-2 mt-2.5 text-slate-950 dark:text-white" {...props} />,
          h4: ({node, ...props}) => <h4 className="text-sm font-bold mb-2 mt-2 text-slate-950 dark:text-white" {...props} />,
          h5: ({node, ...props}) => <h5 className="text-xs font-bold mb-1.5 mt-1.5 text-slate-950 dark:text-white" {...props} />,
          h6: ({node, ...props}) => <h6 className="text-xs font-bold mb-1 mt-1 text-slate-950 dark:text-white" {...props} />,
          strong: ({node, ...props}) => <strong className="font-bold text-slate-950 dark:text-white" {...props} />,
          em: ({node, ...props}) => <em className="italic text-slate-900 dark:text-slate-200" {...props} />,
          code: ({node, ...props}) => <code className="bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-slate-100 px-1.5 py-0.5 rounded text-xs font-mono font-semibold" {...props} />,
          blockquote: ({node, ...props}) => <blockquote className="border-l-4 border-blue-500 pl-3.5 italic my-2.5 text-slate-700 dark:text-slate-300" {...props} />,
          table: ({node, ...props}) => <div className="overflow-x-auto my-3"><table className="w-full text-left border-collapse border border-slate-300 dark:border-slate-700" {...props} /></div>,
          thead: ({node, ...props}) => <thead className="bg-slate-100 dark:bg-slate-800/80" {...props} />,
          th: ({node, ...props}) => <th className="p-2.5 text-xs font-bold text-slate-950 dark:text-white border border-slate-300 dark:border-slate-700 bg-slate-100 dark:bg-slate-800/90" {...props} />,
          td: ({node, ...props}) => <td className="p-2.5 text-xs text-slate-900 dark:text-slate-200 border border-slate-300 dark:border-slate-700 leading-relaxed" {...props} />,
          tr: ({node, ...props}) => <tr className="even:bg-slate-50/50 dark:even:bg-slate-800/30" {...props} />,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )

  const SkeletonResponse = ({ isHybrid }: { isHybrid?: boolean }) => (
    <div className="space-y-3 animate-in fade-in duration-300 py-1">
      <div className={`h-4 w-3/4 rounded-full ${isHybrid ? 'bg-blue-200 dark:bg-blue-900/60' : 'bg-slate-200 dark:bg-slate-700'} animate-pulse`} />
      <div className={`h-4 w-full rounded-full ${isHybrid ? 'bg-blue-200/80 dark:bg-blue-900/40' : 'bg-slate-200/80 dark:bg-slate-700/80'} animate-pulse`} style={{ animationDelay: '0.15s' }} />
      <div className={`h-4 w-5/6 rounded-full ${isHybrid ? 'bg-blue-200/60 dark:bg-blue-900/30' : 'bg-slate-200/60 dark:bg-slate-700/60'} animate-pulse`} style={{ animationDelay: '0.3s' }} />
    </div>
  )

  return (
    <div className="flex-1 flex flex-col overflow-hidden max-w-6xl mx-auto w-full px-4 py-8">
      {/* Active RAG Settings Banner */}
      <div className="flex items-center justify-between px-3 py-1.5 mb-3 bg-card/60 backdrop-blur border rounded-xl text-xs text-muted-foreground shadow-sm">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-foreground">
            {comparisonMode ? "Comparing 3 Models:" : `RAG: ${engine === 'lightrag' ? 'LightRAG' : 'GraphRAG'}`}
          </span>
          {comparisonMode ? (
            <span className="bg-primary/10 text-primary px-2 py-0.5 rounded font-mono text-[10px]">
              Naive vs LightRAG ({(lightragMode || 'hybrid').toUpperCase()}) vs GraphRAG ({(graphragMethod || 'drift').toUpperCase()})
            </span>
          ) : (
            <span className="bg-muted px-2 py-0.5 rounded font-mono text-[10px] text-foreground">
              Mode: {ragMode.toUpperCase()} • Top-K: {topK} • Lvl: {communityLevel}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-[10px]">
          <span className={`px-2 py-0.5 rounded font-medium ${critique ? 'bg-amber-500/10 text-amber-600 dark:text-amber-400' : 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'}`}>
            {critique ? 'Critique: Active' : 'Direct Streaming'}
          </span>
        </div>
      </div>

      <div 
        ref={scrollRef}
        className="flex-1 overflow-y-auto space-y-6 pb-24 scroll-smooth pr-2"
      >
        {messages.map((msg) => (
          <div key={msg.id} className={`flex gap-4 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`flex gap-4 w-full ${msg.role === 'user' ? 'flex-row-reverse max-w-[85%]' : 'flex-row'}`}>
              <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
                msg.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted border text-muted-foreground'
              }`}>
                {msg.role === 'user' ? <User className="w-5 h-5" /> : <Bot className="w-5 h-5" />}
              </div>
              
              <div className="flex-1 space-y-4 min-w-0">
                {msg.comparison ? (
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    {/* Naive Response */}
                    <div className="space-y-3">
                      <div className="flex items-center gap-2 px-1">
                        <span className="text-[11px] font-bold text-slate-700 dark:text-slate-200 uppercase tracking-wider bg-slate-100 dark:bg-slate-800 px-2.5 py-1 rounded-md border border-slate-200 dark:border-slate-700">Naive RAG</span>
                        {isLoading && !msg.comparison.naive.content && <div className="w-1.5 h-1.5 rounded-full bg-slate-500 animate-pulse" />}
                      </div>
                      <div className="p-4 rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-sm h-full overflow-hidden">
                        {msg.comparison.naive.content ? (
                          <MarkdownContent content={msg.comparison.naive.content} role="assistant" />
                        ) : (
                          <SkeletonResponse />
                        )}
                      </div>
                    </div>
                    {/* GraphRAG Response */}
                    <div className="space-y-3">
                      <div className="flex items-center gap-2 px-1">
                        <span className="text-[11px] font-bold text-emerald-800 dark:text-emerald-300 uppercase tracking-wider bg-emerald-50 dark:bg-emerald-950/40 px-2.5 py-1 rounded-md border border-emerald-200 dark:border-emerald-800">
                          GraphRAG ({(graphragMethod || 'drift').toUpperCase()})
                        </span>
                        {isLoading && !msg.comparison.drift.content && <div className="w-1.5 h-1.5 rounded-full bg-emerald-600 animate-pulse" />}
                      </div>
                      <div className="p-4 rounded-2xl bg-white dark:bg-slate-900 border border-emerald-200 dark:border-emerald-900 shadow-sm h-full overflow-hidden">
                        {msg.comparison.drift.content ? (
                          <MarkdownContent content={msg.comparison.drift.content} role="assistant" />
                        ) : (
                          <SkeletonResponse />
                        )}
                      </div>
                    </div>
                    {/* LightRAG Response */}
                    <div className="space-y-3">
                      <div className="flex items-center gap-2 px-1">
                        <span className="text-[11px] font-bold text-blue-800 dark:text-blue-300 uppercase tracking-wider bg-blue-50 dark:bg-blue-950/40 px-2.5 py-1 rounded-md border border-blue-200 dark:border-blue-800">
                          LightRAG ({(lightragMode || 'hybrid').toUpperCase()})
                        </span>
                        {isLoading && !msg.comparison.hybrid.content && <div className="w-1.5 h-1.5 rounded-full bg-blue-600 animate-pulse" />}
                      </div>
                      <div className="p-4 rounded-2xl bg-white dark:bg-slate-900 border border-blue-200 dark:border-blue-900 shadow-sm h-full overflow-hidden">
                        {msg.comparison.hybrid.content ? (
                          <MarkdownContent content={msg.comparison.hybrid.content} role="assistant" />
                        ) : (
                          <SkeletonResponse isHybrid />
                        )}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="max-w-[85%]">
                    <div className={`p-4 rounded-2xl ${
                      msg.role === 'user' 
                        ? 'bg-primary text-primary-foreground rounded-tr-none' 
                        : 'bg-card border rounded-tl-none shadow-sm'
                    }`}>
                      {msg.role === 'assistant' && !msg.content && isLoading ? (
                        <SkeletonResponse isHybrid />
                      ) : (
                        <MarkdownContent content={msg.content || ''} role={msg.role} />
                      )}
                    </div>
                    
                    {msg.sources && msg.sources.length > 0 && (
                      <div className="mt-4 animate-in fade-in slide-in-from-top-2">
                        <h4 className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-2 px-1">Sources Found</h4>
                        <div className="space-y-2">
                          {msg.sources.map((src, idx) => (
                            <ReferenceCard key={idx} reference={src} />
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Input Area */}
      <div className="absolute bottom-8 left-4 right-4 max-w-6xl mx-auto">
        <div className="bg-card border rounded-2xl shadow-xl flex items-center p-2 focus-within:ring-2 focus-within:ring-primary/20 transition-all">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                handleSend()
              }
            }}
            placeholder="Ask a legal question..."
            className="flex-1 bg-transparent border-none focus:ring-0 text-sm py-3 px-4 resize-none max-h-32 min-h-[44px]"
            rows={1}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isLoading}
            className="p-3 bg-primary text-primary-foreground rounded-xl hover:opacity-90 disabled:opacity-50 transition-all ml-2 shadow-lg hover:shadow-primary/20"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
        <p className="text-[10px] text-center text-muted-foreground mt-3">
          Powered by LightRAG & DeepSeek. Citations are derived from the uploaded legal database.
        </p>
      </div>
    </div>
  )
}