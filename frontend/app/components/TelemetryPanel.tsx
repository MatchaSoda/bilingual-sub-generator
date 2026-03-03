import React from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Paper from '@mui/material/Paper';
import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import CircularProgress from '@mui/material/CircularProgress';

import ActivityIcon from '@mui/icons-material/Assessment';
import StatusIcon from '@mui/icons-material/FiberManualRecord';

interface TelemetryPanelProps {
  logs: string[];
  status: string;
}

const TelemetryPanel = ({ logs, status }: TelemetryPanelProps) => (
  <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', gap: 3, animate: 'fadeIn 0.5s ease-out' }}>
    <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', px: 2 }}>
      <Typography 
        variant="h4" 
        sx={{ 
          fontWeight: 900, 
          fontStyle: 'italic', 
          textTransform: 'uppercase', 
          display: 'flex', 
          alignItems: 'center', 
          gap: 2,
          color: 'white'
        }}
      >
        <ActivityIcon sx={{ fontSize: 40, color: 'primary.main' }} />
        Telemetry
      </Typography>
      
      <Chip
        icon={status === 'processing' ? <CircularProgress size={16} color="inherit" /> : <StatusIcon />}
        label={`Status: ${status}`}
        variant="outlined"
        color={status === 'processing' ? 'primary' : 'default'}
        sx={{ 
          px: 2, 
          py: 2.5, 
          borderRadius: 2, 
          fontWeight: 900, 
          textTransform: 'uppercase', 
          letterSpacing: 2,
          borderWidth: 2,
          bgcolor: status === 'processing' ? 'rgba(59, 130, 246, 0.1)' : 'rgba(0,0,0,0.5)',
          animation: status === 'processing' ? 'pulse 2s infinite' : 'none'
        }}
      />
    </Box>

    <Paper
      elevation={0}
      sx={{
        flex: 1,
        bgcolor: 'rgba(5, 7, 10, 0.6)',
        border: '1px solid rgba(255, 255, 255, 0.05)',
        borderRadius: 2,
        p: 4,
        fontFamily: 'monospace',
        overflowY: 'auto',
        display: 'flex',
        flexDirection: 'column',
        position: 'relative',
        '&::-webkit-scrollbar': { width: 8 },
        '&::-webkit-scrollbar-thumb': { bgcolor: 'rgba(255,255,255,0.1)', borderRadius: 1 }
      }}
    >
      {logs.length === 0 ? (
        <Box sx={{ 
          height: '100%', 
          display: 'flex', 
          alignItems: 'center', 
          justifyContent: 'center',
          opacity: 0.05,
          userSelect: 'none'
        }}>
          <Typography variant="h1" sx={{ fontWeight: 900, fontStyle: 'italic', textTransform: 'uppercase', fontSize: '12vw' }}>
            Standby
          </Typography>
        </Box>
      ) : (
        <Stack spacing={1}>
          {logs.map((l, i) => (
            <Box 
              key={i} 
              sx={{ 
                py: 1, 
                px: 3, 
                borderLeft: '2px solid rgba(59, 130, 246, 0.3)',
                color: 'text.secondary',
                fontWeight: 700,
                fontSize: 13,
                '&:hover': { color: 'white', bgcolor: 'rgba(255,255,255,0.02)' }
              }}
            >
              {l}
            </Box>
          ))}
        </Stack>
      )}
    </Paper>
  </Box>
);

export default TelemetryPanel;
