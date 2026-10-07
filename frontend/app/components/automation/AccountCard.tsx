import React, { useEffect, useRef, useState } from 'react';
import Box from '@mui/material/Box';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogActions from '@mui/material/DialogActions';
import CircularProgress from '@mui/material/CircularProgress';
import Alert from '@mui/material/Alert';

import AccountIcon from '@mui/icons-material/AccountCircle';
import QrIcon from '@mui/icons-material/QrCode2';

import { automationApi, AccountStatus, QrSession, errorMessage } from '../../../src/api';
import { cardSx, formatClock, formatRelative, serverNow } from '../../../src/automation';
import QrCode from './QrCode';

const DAY = 86400;

// B 站登录状态 + 扫码登录。投稿用的 cookies.json 就是这里写的（以前只能在终端里 biliup login）
const AccountCard = ({ onChange }: { onChange?: (account: AccountStatus) => void }) => {
  const [account, setAccount] = useState<AccountStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [session, setSession] = useState<QrSession | null>(null);
  const [qrError, setQrError] = useState('');
  const [starting, setStarting] = useState(false);
  const pollRef = useRef<any>(null);

  const load = async (check = true) => {
    try {
      const res = await automationApi.account(check);
      setAccount(res.data);
      onChange?.(res.data);
    } catch (e) {
      setAccount({ exists: false, logged_in: false, error: errorMessage(e) });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    return () => clearInterval(pollRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const startQr = async () => {
    clearInterval(pollRef.current);
    // 二维码接口要等 B 站返回，可能比较慢；轮询拿状态
    setStarting(true);
    setQrError('');
    setSession(null);
    try {
      const res = await automationApi.startQrLogin();
      setSession(res.data);
      pollRef.current = setInterval(async () => {
        try {
          const poll = await automationApi.qrLoginStatus(res.data.id);
          setSession(poll.data);
          if (poll.data.state !== 'waiting') {
            clearInterval(pollRef.current);
            if (poll.data.state === 'success') load();
          }
        } catch (e) {
          clearInterval(pollRef.current);
          setQrError(errorMessage(e));
        }
      }, 2000);
    } catch (e) {
      setQrError(errorMessage(e, '获取二维码失败'));
    } finally {
      setStarting(false);
    }
  };

  const openDialog = () => {
    setDialogOpen(true);
    startQr();
  };

  const closeDialog = () => {
    clearInterval(pollRef.current);
    setDialogOpen(false);
    // 还在等扫码就让后端停掉那个进程
    if (session?.state === 'waiting') automationApi.cancelQrLogin(session.id).catch(() => undefined);
  };

  const daysLeft = account?.expires_at ? (account.expires_at - serverNow()) / DAY : null;
  let chip: { label: string; color: 'success' | 'warning' | 'error' | 'default' } = { label: '检查中', color: 'default' };
  if (!loading && account) {
    if (!account.logged_in) chip = { label: '未登录', color: 'error' };
    else if (account.valid === false) chip = { label: '登录已失效', color: 'error' };
    else if (daysLeft !== null && daysLeft < 14) chip = { label: `${Math.max(0, Math.floor(daysLeft))} 天后过期`, color: 'warning' };
    else if (account.valid) chip = { label: '已登录', color: 'success' };
    else chip = { label: '已登录（未验证）', color: 'default' };
  }

  return (
    <Paper elevation={0} sx={{ ...cardSx, display: 'flex', flexDirection: 'column', gap: 1.5 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
        <AccountIcon color="secondary" />
        <Typography variant="subtitle1" sx={{ fontWeight: 900, flex: 1 }}>B 站投稿账号</Typography>
        <Chip size="small" label={chip.label} color={chip.color} variant="outlined" sx={{ fontWeight: 700 }} />
      </Box>

      {loading ? (
        <CircularProgress size={20} />
      ) : account?.logged_in ? (
        <Box sx={{ display: 'grid', gridTemplateColumns: 'auto 1fr', columnGap: 2, rowGap: 0.5, fontSize: 13 }}>
          <Typography variant="caption" color="text.secondary">用户</Typography>
          <Typography variant="body2" sx={{ fontWeight: 700 }}>
            {account.uname || '—'}{account.mid ? `（UID ${account.mid}）` : ''}
          </Typography>
          <Typography variant="caption" color="text.secondary">有效期</Typography>
          <Typography variant="body2">
            {account.expires_at ? `${formatClock(account.expires_at)}（${formatRelative(account.expires_at)}到期）` : '—'}
          </Typography>
          <Typography variant="caption" color="text.secondary">更新于</Typography>
          <Typography variant="body2">{formatClock(account.updated_at)}</Typography>
        </Box>
      ) : (
        <Typography variant="body2" color="text.secondary">
          还没有登录信息，投稿会失败。用 B 站手机 App 扫码登录。
        </Typography>
      )}
      {account?.error && <Alert severity={account.logged_in ? 'warning' : 'error'} sx={{ py: 0 }}>{account.error}</Alert>}

      <Box>
        <Button variant="outlined" size="small" startIcon={<QrIcon />} onClick={openDialog} sx={{ px: 2, py: 0.75 }}>
          {account?.logged_in ? '重新扫码登录' : '扫码登录'}
        </Button>
      </Box>

      <Dialog open={dialogOpen} onClose={closeDialog} maxWidth="xs" fullWidth>
        <DialogTitle sx={{ fontWeight: 900 }}>B 站扫码登录</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
          {starting && <CircularProgress sx={{ my: 6 }} />}
          {session && session.state === 'waiting' && (
            <>
              <Box sx={{ p: 1.5, bgcolor: '#fff', borderRadius: 1 }}>
                <QrCode value={session.url} />
              </Box>
              <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center' }}>
                打开 B 站手机 App → 右上角扫一扫 → 确认登录。<br />
                二维码 {formatRelative(session.expires_at)}过期。登录成功后旧的登录信息会备份。
              </Typography>
            </>
          )}
          {session?.state === 'success' && <Alert severity="success" sx={{ width: '100%' }}>{session.message}</Alert>}
          {session && (session.state === 'expired' || session.state === 'failed') && (
            <Alert severity={session.state === 'expired' ? 'warning' : 'error'} sx={{ width: '100%' }}>{session.message}</Alert>
          )}
          {qrError && <Alert severity="error" sx={{ width: '100%' }}>{qrError}</Alert>}
        </DialogContent>
        <DialogActions>
          {session && session.state !== 'waiting' && session.state !== 'success' && (
            <Button onClick={startQr}>重新生成二维码</Button>
          )}
          <Button onClick={closeDialog}>{session?.state === 'success' ? '完成' : '关闭'}</Button>
        </DialogActions>
      </Dialog>
    </Paper>
  );
};

export default AccountCard;
