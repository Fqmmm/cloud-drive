package com.jiayuan.drive.auth;

import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import javax.sql.DataSource;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class HealthControllerTest {
    @Test
    void livenessDoesNotContactDatabase() throws Exception {
        DataSource source = mock(DataSource.class);
        mvc(source).perform(get("/health/live"))
                .andExpect(status().isOk()).andExpect(content().json("{\"status\":\"UP\"}"));
        verifyNoInteractions(source);
    }

    @Test
    void readinessRecoversAndClosesResourcesWithoutLeakingFailures() throws Exception {
        DataSource source = mock(DataSource.class);
        Connection connection = mock(Connection.class);
        Statement statement = mock(Statement.class);
        ResultSet result = mock(ResultSet.class);
        when(source.getConnection()).thenThrow(new SQLException("sensitive connection details"))
                .thenReturn(connection);
        when(connection.createStatement()).thenReturn(statement);
        when(statement.executeQuery("SELECT 1")).thenReturn(result);
        when(result.next()).thenReturn(true);
        when(result.getInt(1)).thenReturn(1);

        MockMvc mvc = mvc(source);
        mvc.perform(get("/health/ready")).andExpect(status().isServiceUnavailable())
                .andExpect(content().json("{\"status\":\"DOWN\"}", true));
        mvc.perform(get("/health/ready")).andExpect(status().isOk())
                .andExpect(content().json("{\"status\":\"UP\"}", true));
        verify(statement).setQueryTimeout(2);
        verify(result).close();
        verify(statement).close();
        verify(connection).close();
    }

    @Test
    void failedQueryClosesBorrowedConnection() throws Exception {
        DataSource source = mock(DataSource.class);
        Connection connection = mock(Connection.class);
        Statement statement = mock(Statement.class);
        when(source.getConnection()).thenReturn(connection);
        when(connection.createStatement()).thenReturn(statement);
        when(statement.executeQuery("SELECT 1")).thenThrow(new SQLException("query failure"));
        mvc(source).perform(get("/health/ready")).andExpect(status().isServiceUnavailable());
        verify(statement).close();
        verify(connection).close();
    }

    private MockMvc mvc(DataSource source) {
        return MockMvcBuilders.standaloneSetup(new HealthController(source)).build();
    }
}
