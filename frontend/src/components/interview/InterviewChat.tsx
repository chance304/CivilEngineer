'use client';

import { useState, useRef, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Send, Loader2, Bot, User } from 'lucide-react';
import { designApi } from '@/lib/api';
import { wsManager } from '@/lib/websocket';
import { useAppStore } from '@/store/useAppStore';

interface Message {
  role: 'assistant' | 'user';
  content: string;
  timestamp: Date;
}

interface InterviewChatProps {
  projectId: string;
}

export function InterviewChat({ projectId }: InterviewChatProps) {
  const router = useRouter();
  const { accessToken } = useAppStore();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isThinking, setIsThinking] = useState(false);
  const [isStarting, setIsStarting] = useState(false);
  const [questionNum, setQuestionNum] = useState(0);
  const [totalQuestions] = useState(8);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    startSession();
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  async function startSession() {
    setIsStarting(true);
    try {
      const { session_id } = await designApi.start(projectId);
      setSessionId(session_id);

      if (accessToken) {
        wsManager.connect(session_id, accessToken);
        wsManager.on('interview.question', (data) => {
          const d = data as { prompt: string; question_num?: number };
          setMessages((prev) => [
            ...prev,
            { role: 'assistant', content: d.prompt, timestamp: new Date() },
          ]);
          if (d.question_num) setQuestionNum(d.question_num);
          setIsThinking(false);
        });
        wsManager.on('design.progress', () => {
          // Interview finished — redirect to design job page
          router.push(`/projects/${projectId}/design/${session_id}`);
        });
      }
    } catch {
      setMessages([{
        role: 'assistant',
        content: 'Please describe your building requirements: number of floors, BHK configuration, style, Vastu preference, and any special rooms.',
        timestamp: new Date(),
      }]);
    } finally {
      setIsStarting(false);
    }
  }

  async function sendMessage() {
    if (!input.trim() || !sessionId || isThinking) return;

    const userMsg: Message = { role: 'user', content: input.trim(), timestamp: new Date() };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setIsThinking(true);

    try {
      await designApi.sendInterviewAnswer(projectId, sessionId, userMsg.content);
    } catch {
      setIsThinking(false);
    }
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  return (
    <div className="flex flex-col bg-white rounded-xl border border-gray-200 overflow-hidden flex-1">
      {/* Progress bar */}
      {questionNum > 0 && (
        <div className="px-4 py-2 border-b border-gray-100 flex items-center gap-3">
          <span className="text-xs text-gray-500">{questionNum} of {totalQuestions} questions</span>
          <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 rounded-full transition-all"
              style={{ width: `${Math.min(100, (questionNum / totalQuestions) * 100)}%` }}
            />
          </div>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 min-h-0">
        {isStarting && (
          <div className="flex items-center gap-2 text-sm text-gray-400">
            <Loader2 className="w-4 h-4 animate-spin" />
            Starting session…
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
            <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${
              msg.role === 'assistant' ? 'bg-blue-100' : 'bg-gray-100'
            }`}>
              {msg.role === 'assistant' ? (
                <Bot className="w-4 h-4 text-blue-600" />
              ) : (
                <User className="w-4 h-4 text-gray-600" />
              )}
            </div>
            <div className={`max-w-[80%] px-3 py-2 rounded-2xl text-sm ${
              msg.role === 'assistant'
                ? 'bg-gray-100 text-gray-800 rounded-tl-sm'
                : 'bg-blue-600 text-white rounded-tr-sm'
            }`}>
              {msg.content}
            </div>
          </div>
        ))}
        {isThinking && (
          <div className="flex gap-3">
            <div className="w-7 h-7 rounded-full bg-blue-100 flex items-center justify-center shrink-0">
              <Bot className="w-4 h-4 text-blue-600" />
            </div>
            <div className="bg-gray-100 px-3 py-2 rounded-2xl rounded-tl-sm flex gap-1 items-center h-8">
              <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
              <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
              <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="border-t border-gray-100 p-3 flex gap-2">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Type your answer…"
          rows={1}
          className="flex-1 resize-none px-3 py-2 border border-gray-300 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button
          onClick={sendMessage}
          disabled={!input.trim() || isThinking}
          className="px-3 py-2 bg-blue-600 text-white rounded-xl hover:bg-blue-700 disabled:opacity-40 transition-colors"
          aria-label="Send"
        >
          <Send className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
