import React, { useCallback, useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/Card';
import { Mail, Bell, Plus, Trash2, CheckCircle2 } from 'lucide-react';
import { USE_MOCK_DATA, apiClient } from '../api/config';

interface NotificationRecipient {
  email: string;
  is_active: boolean;
  created_at: string | null;
}

const NOTIFICATION_RECIPIENTS_ENDPOINT = '/notification-recipients';

const mockRecipients: NotificationRecipient[] = [
  { email: 'admin@example.com', is_active: true, created_at: '2026-04-20' },
  { email: 'manager@example.com', is_active: true, created_at: '2026-04-21' },
];

const formatCreatedAt = (createdAt: string | null) => {
  if (!createdAt) return '-';
  return createdAt.split('T')[0];
};

export const AlertsPage: React.FC = () => {
  const [email, setEmail] = useState('');
  const [recipients, setRecipients] = useState<NotificationRecipient[]>(
    USE_MOCK_DATA ? mockRecipients : []
  );
  const [successMsg, setSuccessMsg] = useState('');

  const fetchRecipients = useCallback(async () => {
    const res = await apiClient.get<NotificationRecipient[]>(NOTIFICATION_RECIPIENTS_ENDPOINT);
    setRecipients(res.data);
  }, []);

  useEffect(() => {
    if (!USE_MOCK_DATA) {
      apiClient.get<NotificationRecipient[]>(NOTIFICATION_RECIPIENTS_ENDPOINT)
        .then(res => setRecipients(res.data))
        .catch(err => console.error('Failed to fetch notification recipients:', err));
    }
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    const trimmedEmail = email.trim();
    if (!trimmedEmail) return;

    const newRecipient: NotificationRecipient = {
      email: trimmedEmail,
      is_active: true,
      created_at: new Date().toISOString().split('T')[0],
    };

    if (!USE_MOCK_DATA) {
      try {
        await apiClient.post(NOTIFICATION_RECIPIENTS_ENDPOINT, { emails: [trimmedEmail] });
        await fetchRecipients();
        setSuccessMsg('이메일이 성공적으로 등록되었습니다.');
      } catch (error) {
        console.error('Failed to add notification recipient:', error);
        alert('등록에 실패했습니다.');
        return;
      }
    } else {
      setRecipients(prev => [
        ...prev.filter(recipient => recipient.email !== trimmedEmail),
        newRecipient,
      ]);
      setSuccessMsg('이메일이 성공적으로 등록되었습니다.');
    }

    setEmail('');
    setTimeout(() => setSuccessMsg(''), 3000);
  };

  const handleDelete = async (recipientEmail: string) => {
    if (!USE_MOCK_DATA) {
      try {
        await apiClient.delete(`${NOTIFICATION_RECIPIENTS_ENDPOINT}/${encodeURIComponent(recipientEmail)}`);
        setRecipients(prev => prev.filter(recipient => recipient.email !== recipientEmail));
      } catch (error) {
        console.error('Failed to delete notification recipient:', error);
        alert('삭제에 실패했습니다.');
      }
    } else {
      setRecipients(prev => prev.filter(recipient => recipient.email !== recipientEmail));
    }
  };

  const toggleActive = async (recipientEmail: string) => {
    const recipientToToggle = recipients.find(recipient => recipient.email === recipientEmail);
    if (!recipientToToggle) return;

    const nextIsActive = !recipientToToggle.is_active;

    if (!USE_MOCK_DATA) {
      try {
        await apiClient.patch(
          `${NOTIFICATION_RECIPIENTS_ENDPOINT}/${encodeURIComponent(recipientEmail)}`,
          { is_active: nextIsActive }
        );
        setRecipients(prev => prev.map(recipient =>
          recipient.email === recipientEmail ? { ...recipient, is_active: nextIsActive } : recipient
        ));
      } catch (error) {
        console.error('Failed to toggle notification recipient:', error);
        alert('상태 변경에 실패했습니다.');
      }
    } else {
      setRecipients(prev => prev.map(recipient =>
        recipient.email === recipientEmail ? { ...recipient, is_active: nextIsActive } : recipient
      ));
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold tracking-tight text-slate-900">알림 이메일 등록</h2>
        <div className="flex items-center gap-2 text-slate-500 bg-white px-4 py-2 rounded-full shadow-sm border border-slate-200">
          <Bell size={18} />
          <span className="text-sm font-medium">화재 발생 시 실시간 알림 수신</span>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card className="md:col-span-1 h-fit">
          <CardHeader className="bg-slate-50 border-b border-slate-100 rounded-t-xl">
            <CardTitle className="text-lg font-semibold text-slate-800 flex items-center gap-2">
              <Mail size={20} className="text-blue-500" />
              새 이메일 등록
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-6">
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label htmlFor="email" className="block text-sm font-medium text-slate-700 mb-1">
                  이메일 주소
                </label>
                <input
                  type="email"
                  id="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full px-4 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-colors"
                  placeholder="example@domain.com"
                  required
                />
              </div>
              <button
                type="submit"
                className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2.5 rounded-lg font-medium transition-colors"
              >
                <Plus size={18} />
                등록하기
              </button>

              {successMsg && (
                <div className="flex items-center gap-2 text-green-600 bg-green-50 p-3 rounded-lg text-sm font-medium mt-4">
                  <CheckCircle2 size={16} />
                  {successMsg}
                </div>
              )}
            </form>
          </CardContent>
        </Card>

        <Card className="md:col-span-2">
          <CardHeader className="bg-slate-50 border-b border-slate-100 rounded-t-xl">
            <CardTitle className="text-lg font-semibold text-slate-800 flex items-center justify-between">
              <span>등록된 이메일 목록</span>
              <span className="bg-blue-100 text-blue-700 text-xs px-2.5 py-1 rounded-full">
                총 {recipients.length}개
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {recipients.length === 0 ? (
              <div className="text-center py-12 text-slate-500">
                <Mail size={48} className="mx-auto text-slate-300 mb-4" />
                <p>등록된 이메일이 없습니다.</p>
              </div>
            ) : (
              <ul className="divide-y divide-slate-100">
                {recipients.map((recipient) => (
                  <li key={recipient.email} className="flex items-center justify-between p-4 hover:bg-slate-50 transition-colors">
                    <div className="flex items-center gap-4">
                      <div className={`w-10 h-10 rounded-full flex items-center justify-center ${recipient.is_active ? 'bg-blue-100 text-blue-600' : 'bg-slate-100 text-slate-400'}`}>
                        <Mail size={20} />
                      </div>
                      <div>
                        <p className={`font-medium ${recipient.is_active ? 'text-slate-900' : 'text-slate-500 line-through'}`}>
                          {recipient.email}
                        </p>
                        <p className="text-xs text-slate-500">등록일 {formatCreatedAt(recipient.created_at)}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <button
                        onClick={() => toggleActive(recipient.email)}
                        className={`px-3 py-1 text-xs font-medium rounded-full border transition-colors ${
                          recipient.is_active
                            ? 'border-green-200 bg-green-50 text-green-700 hover:bg-green-100'
                            : 'border-slate-200 bg-slate-50 text-slate-600 hover:bg-slate-100'
                        }`}
                      >
                        {recipient.is_active ? '수신 중' : '수신 거부'}
                      </button>
                      <button
                        onClick={() => handleDelete(recipient.email)}
                        className="p-2 text-slate-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                        title="삭제"
                      >
                        <Trash2 size={18} />
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
};
