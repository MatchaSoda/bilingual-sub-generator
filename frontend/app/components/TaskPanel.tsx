import React from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import TextField from '@mui/material/TextField';
import Button from '@mui/material/Button';
import Paper from '@mui/material/Paper';
import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';

import ZapIcon from '@mui/icons-material/Bolt';
import SettingsIcon from '@mui/icons-material/Settings';

interface TaskPanelProps {
  form: any;
  setForm: (form: any) => void;
  startTask: () => void;
  status: string;
  onNavigate: (tab: string) => void;
}

const TaskPanel = ({ form, setForm, startTask, status, onNavigate }: TaskPanelProps) => {
  return (
    <Box 
      sx={{ 
        height: '100%', 
        display: 'flex', 
        flexDirection: 'column', 
        alignItems: 'center', 
        justifyContent: 'center',
        gap: 6,
        animate: 'fadeIn 0.5s ease-out'
      }}
    >
      <Box sx={{ textAlign: 'center' }}>
        <Typography 
          variant="h2" 
          sx={{ 
            fontWeight: 900, 
            fontStyle: 'italic', 
            textTransform: 'uppercase',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 2,
            mb: 1,
            color: 'white',
            textShadow: '0 10px 30px rgba(0,0,0,0.5)'
          }}
        >
          <ZapIcon sx={{ fontSize: 60, color: 'primary.main' }} />
          Initiate
        </Typography>
        <Typography 
          variant="overline" 
          sx={{ 
            fontSize: 14, 
            letterSpacing: 4, 
            color: 'text.secondary',
            fontWeight: 700
          }}
        >
          大师级 1:1 物理渲染实验室。
        </Typography>
      </Box>

      <Paper 
        elevation={0}
        sx={{ 
          width: '100%', 
          maxWidth: 800, 
          p: 5, 
          borderRadius: 2,
          bgcolor: 'rgba(255, 255, 255, 0.03)', 
          border: '1px solid rgba(255, 255, 255, 0.05)',
          backdropFilter: 'blur(20px)',
          display: 'flex',
          flexDirection: 'column',
          gap: 4
        }}
      >
        <TextField
          fullWidth
          variant="outlined"
          placeholder="PASTE YOUTUBE / BILIBILI LINK"
          value={form.url}
          onChange={(e) => setForm({...form, url: e.target.value})}
          sx={{
            '& .MuiOutlinedInput-root': {
              borderRadius: 1,
              fontSize: '1.2rem',
              fontWeight: 900,
              letterSpacing: 1.5,
              backgroundColor: 'rgba(0,0,0,0.3)',
              '& fieldset': { borderColor: 'rgba(255,255,255,0.1)' },
              '&:hover fieldset': { borderColor: 'primary.main' },
              '&.Mui-focused fieldset': { borderColor: 'primary.main' },
            },
            '& input': { textAlign: 'center' }
          }}
        />

        <Stack 
          direction="row" 
          justifyContent="center" 
          alignItems="center" 
          spacing={3}
        >
          <Chip 
            label={`ASR: ${form.model}`} 
            variant="outlined" 
            sx={{ 
              fontWeight: 900, 
              textTransform: 'uppercase', 
              fontSize: 10, 
              borderColor: 'rgba(59, 130, 246, 0.3)',
              color: 'primary.light'
            }} 
          />
          <Chip 
            label={`Translator: ${form.translation_model?.replace('gemini-', 'G-') || 'Flash'}`} 
            variant="outlined" 
            sx={{ 
              fontWeight: 900, 
              textTransform: 'uppercase', 
              fontSize: 10, 
              borderColor: 'rgba(20, 184, 166, 0.3)',
              color: 'secondary.light'
            }} 
          />
          <Button
            size="small"
            startIcon={<SettingsIcon sx={{ fontSize: 14 }} />}
            onClick={() => onNavigate('settings')}
            sx={{ 
              color: 'text.secondary', 
              fontSize: 10, 
              fontWeight: 900,
              '&:hover': { color: 'white', bgcolor: 'transparent' }
            }}
          >
            修改设置
          </Button>
        </Stack>
      </Paper>

      <Button
        variant="contained"
        size="large"
        disabled={status === 'processing'}
        onClick={startTask}
        endIcon={<ZapIcon />}
        sx={{
          py: 3,
          px: 12,
          fontSize: '1.5rem',
          fontWeight: 900,
          fontStyle: 'italic',
          textTransform: 'uppercase',
          boxShadow: '0 20px 50px rgba(59, 130, 246, 0.3)',
          transition: 'all 0.3s ease',
          '&:hover': {
            transform: 'translateY(-5px)',
            boxShadow: '0 30px 60px rgba(59, 130, 246, 0.4)',
          }
        }}
      >
        {status === 'processing' ? 'Processing...' : 'Engage Engine'}
      </Button>
    </Box>
  );
};

export default TaskPanel;
