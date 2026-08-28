package cn.sutone.cut.infrastructure.config;

import com.zaxxer.hikari.HikariDataSource;
import org.mybatis.spring.annotation.MapperScan;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;

import javax.sql.DataSource;

/**
 * MyBatis 持久化配置（仅在 mysql profile 激活时生效）。
 *
 * <p>默认(local) profile 用内存仓储 {@code InMemory*Repository}，不连接数据库。
 * 切换 mysql profile 后：手动建 {@link DataSource}（因 base application.yml 已排除
 * DataSourceAutoConfiguration），并由 {@code @MapperScan} 注册 mapper 接口。</p>
 */
@Configuration
@Profile("mysql")
@MapperScan("cn.sutone.cut.infrastructure.persistence.mapper")
public class MybatisConfig {

    @Bean
    public DataSource dataSource(
            @Value("${spring.datasource.url}") String url,
            @Value("${spring.datasource.username}") String username,
            @Value("${spring.datasource.password}") String password,
            @Value("${spring.datasource.driver-class-name}") String driverClassName) {
        HikariDataSource dataSource = new HikariDataSource();
        dataSource.setJdbcUrl(url);
        dataSource.setUsername(username);
        dataSource.setPassword(password);
        dataSource.setDriverClassName(driverClassName);
        return dataSource;
    }
}
