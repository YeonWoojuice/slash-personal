package com.likelion.slash.observability;

import static com.likelion.slash.jooq.Tables.USERS;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.likelion.slash.auth.AuthenticatedUserService;
import com.likelion.slash.auth.MeController;
import com.likelion.slash.common.error.GlobalExceptionHandler;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.SQLException;
import java.util.regex.Pattern;
import org.jooq.SQLDialect;
import org.jooq.exception.DataAccessException;
import org.jooq.impl.DSL;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class Bounded5xxContractTest {
    @Test
    void cancellationPredicateMatchesCurrentJooqMeLookup() throws Exception {
        var query = DSL.using(SQLDialect.POSTGRES).selectFrom(USERS)
                .where(USERS.COGNITO_SUB.eq("synthetic"));
        String jdbcQuery = query.getSQL().replace("?", "$1").replace("\"", "")
                .replaceAll("\\s+", " ").trim();
        String script = Files.readString(Path.of("../../observability/personal/sql/db-query-cancel-one.sql"));
        var matcher = Pattern.compile("expected_query constant text := '([^']+)';").matcher(script);
        assertThat(matcher.find()).isTrue();
        assertThat(jdbcQuery).isEqualTo(matcher.group(1));
    }

    @Test
    void cancelledQueryMapsTo500WithoutReturningSqlDetails() throws Exception {
        var service = mock(AuthenticatedUserService.class);
        when(service.current()).thenThrow(new DataAccessException("synthetic query cancelled",
                new SQLException("synthetic cancellation", "57014")));
        var mvc = MockMvcBuilders.standaloneSetup(new MeController(service))
                .setControllerAdvice(new GlobalExceptionHandler()).build();
        mvc.perform(get("/api/v1/me"))
                .andExpect(status().isInternalServerError())
                .andExpect(jsonPath("$.error.code").value("INTERNAL_ERROR"))
                .andExpect(jsonPath("$.error.message").value("처리 중 문제가 발생했습니다."));
    }
}
