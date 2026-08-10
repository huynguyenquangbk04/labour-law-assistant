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
  }
}

export default function ChatInterface({ comparisonMode, critique }: { comparisonMode: boolean; critique: boolean }) {
  const [messages, setMessages] = useState<Message[]>([
    { id: 'initial', role: 'assistant', content: 'Hello! I am your Traffic Law Assistant. How can I help you today?' }
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
        hybrid: { content: '', sources: [] } 
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
          critique
        })
      })

      if (!response.ok) throw new Error('Network response was not ok')

      if (critique) {
        const data = await response.json()
        setMessages(prev => prev.map(msg => {
          if (msg.id !== assistantMsgId) return msg

          if (comparisonMode && data.naive && data.hybrid) {
            return {
              ...msg,
              comparison: {
                naive: { content: data.naive.response, sources: data.naive.sources ?? [] },
                hybrid: { content: data.hybrid.response, sources: data.hybrid.sources ?? [] }
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
                  if (data.mode === 'naive' && newMsg.comparison) {
                    newMsg.comparison = {
                      ...newMsg.comparison,
                      naive: { ...newMsg.comparison.naive, content: newMsg.comparison.naive.content + data.content }
                    }
                  } else if (data.mode === 'hybrid') {
                    if (newMsg.comparison) {
                      newMsg.comparison = {
                        ...newMsg.comparison,
                        hybrid: { ...newMsg.comparison.hybrid, content: newMsg.comparison.hybrid.content + data.content }
                      }
                    } else {
                      newMsg.content = (newMsg.content || '') + data.content
                    }
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
      role === 'user' ? 'prose-invert' : 'prose-slate dark:prose-invert'
    }`}>
      <ReactMarkdown 
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({node, ...props}) => <p className="leading-relaxed mb-2 last:mb-0" {...props} />,
          ul: ({node, ...props}) => <ul className="list-disc ml-4 mb-2" {...props} />,
          ol: ({node, ...props}) => <ol className="list-decimal ml-4 mb-2" {...props} />,
          li: ({node, ...props}) => <li className="mb-1" {...props} />,
          h1: ({node, ...props}) => <h1 className="text-xl font-bold mb-3" {...props} />,
          h2: ({node, ...props}) => <h2 className="text-lg font-bold mb-2" {...props} />,
          h3: ({node, ...props}) => <h3 className="text-base font-bold mb-2" {...props} />,
          strong: ({node, ...props}) => <strong className="font-bold text-foreground" {...props} />,
          code: ({node, ...props}) => <code className="bg-muted px-1.5 py-0.5 rounded text-xs font-mono" {...props} />,
          blockquote: ({node, ...props}) => <blockquote className="border-l-4 border-primary/20 pl-4 italic my-2" {...props} />,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )

  const SkeletonResponse = ({ isHybrid }: { isHybrid?: boolean }) => (
    <div className="space-y-3 animate-in fade-in duration-500">
      <div className={`h-4 w-3/4 rounded-full bg-gradient-to-r ${isHybrid ? 'from-primary/10 via-primary/20 to-primary/10' : 'from-muted via-muted/50 to-muted'} animate-[pulse_2s_ease-in-out_infinite]`} />
      <div className={`h-4 w-full rounded-full bg-gradient-to-r ${isHybrid ? 'from-primary/10 via-primary/20 to-primary/10' : 'from-muted via-muted/50 to-muted'} animate-[pulse_2s_ease-in-out_infinite]`} style={{ animationDelay: '0.2s' }} />
      <div className={`h-4 w-5/6 rounded-full bg-gradient-to-r ${isHybrid ? 'from-primary/10 via-primary/20 to-primary/10' : 'from-muted via-muted/50 to-muted'} animate-[pulse_2s_ease-in-out_infinite]`} style={{ animationDelay: '0.4s' }} />
    </div>
  )

  return (
    <div className="flex-1 flex flex-col overflow-hidden max-w-6xl mx-auto w-full px-4 py-8">
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
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {/* Naive Response */}
                    <div className="space-y-4">
                      <div className="flex items-center gap-2 px-1">
                        <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-widest bg-muted/50 px-2 py-0.5 rounded">Naive RAG</span>
                        {isLoading && !msg.comparison.naive.content && <div className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-pulse" />}
                      </div>
                      <div className="p-4 rounded-2xl bg-card border rounded-tl-none shadow-sm h-full overflow-hidden">
                        {msg.comparison.naive.content ? (
                          <MarkdownContent content={msg.comparison.naive.content} role="assistant" />
                        ) : (
                          <SkeletonResponse />
                        )}
                      </div>
                    </div>
                    {/* Hybrid Response */}
                    <div className="space-y-4">
                      <div className="flex items-center gap-2 px-1">
                        <span className="text-[10px] font-bold text-primary uppercase tracking-widest bg-primary/10 px-2 py-0.5 rounded">Hybrid GraphRAG</span>
                        {isLoading && !msg.comparison.hybrid.content && <div className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />}
                      </div>
                      <div className="p-4 rounded-2xl border border-primary/20 bg-primary/[0.02] rounded-tl-none shadow-sm h-full overflow-hidden">
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