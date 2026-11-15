FROM maven:3.9.9-eclipse-temurin-17@sha256:f58d59b6273e785ac0a4477f6e9b5ba1d7731c75b906c0f7b34076f1851318cc AS build
WORKDIR /build
COPY share-service/pom.xml pom.xml
COPY share-service/src src
RUN mvn -B verify

FROM eclipse-temurin:17-jre@sha256:0b6521287f850ec1c4b31c9074c5a1ae1d67c5922c3fefd21065c7c32e244d4a
WORKDIR /app
COPY --from=build /build/target/share-service.jar app.jar
COPY --from=build /build/target/classes/com/jiayuan/drive/shares/HealthProbe.class /app/probe/com/jiayuan/drive/shares/HealthProbe.class
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=6s --start-period=20s --retries=3 CMD ["java", "-cp", "/app/probe", "com.jiayuan.drive.shares.HealthProbe"]
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
